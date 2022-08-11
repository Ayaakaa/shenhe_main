import random
from typing import Optional

import aiosqlite
import discord
from discord import Interaction, Message, Role, SelectOption, app_commands
from discord.app_commands import Choice
from discord.ext import commands
from discord.ui import Select
from debug import DefaultView
from utility.apps.FlowApp import FlowApp
from utility.utils import defaultEmbed, errEmbed, log


class GiveAwayCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.debug_toggle = self.bot.debug_toggle
        self.gv_channel_id = 965517075508498452 if not self.debug_toggle else 909595117952856084

    @app_commands.command(name='giveaway設置抽獎', description='設置抽獎')
    @app_commands.checks.has_role('小雪團隊')
    @app_commands.rename(prize='獎品', goal='目標', ticket='參與金額', role='指定國籍', refund_mode='退款模式')
    @app_commands.describe(
        prize='獎品是什麼?',
        goal='到達多少flow幣後進行抽獎?',
        ticket='參與者得花多少flow幣參與抽獎?',
        role='只有哪些身份組擁有著可以參加抽獎?',
        refund_mode='是否要開啟退款模式?')
    @app_commands.choices(refund_mode=[
        Choice(name='是', value=1),
        Choice(name='否', value=0)
    ])
    async def create_giveaway(
            self, i: Interaction,
            prize: str, goal: int, ticket: int, role: Optional[Role] = None, refund_mode: int = 0):
        channel = i.client.get_channel(self.gv_channel_id)
        role_exclusive = f'此抽獎專屬於: {role.mention} 成員' if role is not None else '任何人都可以參加這個抽獎'
        refund_str = '(會退款)' if refund_mode == 1 else '(不會退款)'
        giveaway_view = GiveAwayCog.GiveAwayView(self.bot.db, self.bot, i)
        await i.response.send_message(embed=defaultEmbed(
            ":tada: 抽獎啦!!!",
            f"獎品: {prize}\n"
            f"目前flow幣: 0/{goal}\n"
            f"參加抽獎要付的flow幣: {ticket}\n"
            f"{role_exclusive}\n"
            f'{refund_str}'), view=giveaway_view)
        msg = await i.original_response()
        c: aiosqlite.Cursor = await self.bot.db.cursor()
        role_id = role.id if role is not None else None
        await c.execute('INSERT INTO giveaway (msg_id, prize_name, goal, ticket, role_id, refund_mode_toggle) VALUES (?, ?, ?, ?, ?, ?)', (msg.id, prize, goal, ticket, role_id, refund_mode))
        if role is not None:
            await channel.send(role.mention)
        else:
            role = i.guild.get_role(967035645610573834)
            await channel.send(role.mention)
        await self.bot.db.commit()

    class GiveAwayView(DefaultView):
        def __init__(self, db: aiosqlite.Connection, i: Interaction = None):
            self.db = db
            self.interaction = i
            self.flow_app = FlowApp(self.db)
            self.gv_channel_id = 965517075508498452
            super().__init__(timeout=None)

        async def generate_gv_embed(self, gv_msg_id: int, i: Interaction):
            c = await self.db.cursor()
            await c.execute('SELECT prize_name, goal, ticket, current, role_id, refund_mode_toggle FROM giveaway WHERE msg_id = ?', (gv_msg_id,))
            gv = await c.fetchone()
            role = i.guild.get_role(gv[4])
            role_str = f'此抽獎專屬於: {role.mention} 成員' if role is not None else '任何人都可以參加這個抽獎'
            refund_str = '(會退款)' if gv[5] == 1 else '(不會退款)'
            embed = defaultEmbed(
                ":tada: 抽獎啦!!!",
                f"獎品: {gv[0]}\n"
                f"目前flow幣: {gv[3]}/{gv[1]}\n"
                f"參加抽獎要付的flow幣: {gv[2]}\n"
                f"{role_str}\n"
                f'{refund_str}')
            return embed

        async def ticket_flow_check(self, user_id: int, ticket: int):
            user_flow = await self.flow_app.get_user_flow(user_id)
            if user_flow < ticket:
                msg = errEmbed(
                    '你目前擁有的flow幣不夠!', f'你現在擁有: **{user_flow}** flow\n參加需要: **{ticket}** flow')
                return False, msg
            else:
                return True, None

        async def join_giveaway(self, user_id: int, ticket: int, gv_msg_id: int):
            log(True, False, 'join giveaway',
                f'(user_id={user_id}, ticket={ticket}, gv_msg_id={gv_msg_id})')
            await self.flow_app.transaction(user_id, -int(ticket))
            c = await self.db.cursor()
            await c.execute('SELECT current FROM giveaway WHERE msg_id = ?', (gv_msg_id,))
            current = await c.fetchone()
            current = current[0]
            await c.execute('UPDATE giveaway SET current = ? WHERE msg_id = ?', (current+ticket, gv_msg_id))
            if ticket < 0:
                await c.execute('DELETE FROM giveaway_members WHERE user_id = ? AND msg_id = ?', (user_id, gv_msg_id))
            else:
                await c.execute('INSERT INTO giveaway_members (user_id, msg_id) VALUES (?, ?)', (user_id, gv_msg_id))
            await self.db.commit()

        async def update_gv_msg(self, gv_msg_id: int, interaction: Interaction):
            channel = interaction.client.get_channel(self.gv_channel_id)
            gv_msg = await channel.fetch_message(gv_msg_id)
            embed = await GiveAwayCog.GiveAwayView.generate_gv_embed(self, gv_msg_id, interaction)
            await gv_msg.edit(embed=embed)

        async def check_gv_finish(self, gv_msg_id: int, i: Interaction):
            c = await self.db.cursor()
            await c.execute('SELECT goal FROM giveaway WHERE msg_id = ?', (gv_msg_id,))
            goal = await c.fetchone()
            goal = goal[0]
            await c.execute('SELECT prize_name, refund_mode_toggle, ticket FROM giveaway WHERE msg_id = ? AND current = ?', (gv_msg_id, goal))
            giveaway = await c.fetchone()
            if giveaway is None:
                return
            prize_name = giveaway[0]
            refund_mode_toggle = giveaway[1]
            ticket = giveaway[2]
            await c.execute('SELECT user_id from giveaway_members WHERE msg_id = ?', (gv_msg_id,))
            giveaway_participants = await c.fetchall()
            participant_list = []
            for index, tuple in enumerate(giveaway_participants):
                participant_list.append(tuple[0])
            channel = i.client.get_channel(self.gv_channel_id)
            lulurR = i.client.get_user(665092644883398671)
            winner_id = random.choice(participant_list)
            winner = i.client.get_user(winner_id)
            original_gv_msg: Message = await channel.fetch_message(gv_msg_id)
            await original_gv_msg.delete()
            embed = defaultEmbed(
                "🎉 抽獎結果",
                f"恭喜{winner.mention}獲得價值 **{goal}** flow幣的 **{prize_name}** !")
            await channel.send(f"{lulurR.mention} {winner.mention}")
            await channel.send(embed=embed)
            if refund_mode_toggle == 1:  # 進行退款
                for user_id in participant_list:
                    if winner_id != user_id:  # 如果該ID不是得獎者
                        # 退款入場費/2
                        await self.flow_app.transaction(user_id, int(ticket)/2)
            log(True, False, 'Giveaway Ended',
                f'(gv_msg_id={gv_msg_id}, winner={winner_id})')
            await c.execute('DELETE FROM giveaway WHERE msg_id = ?', (gv_msg_id,))
            await c.execute('DELETE FROM giveaway_members WHERE msg_id = ?', (gv_msg_id,))
            await self.db.commit()

        async def check_if_already_in_gv(self, user_id: int, gv_msg_id: int):
            c = await self.db.cursor()
            await c.execute('SELECT * FROM giveaway_members WHERE msg_id = ? AND user_id = ?', (gv_msg_id, user_id))
            result = await c.fetchone()
            if result is not None:
                embed = errEmbed('你已經參加過這個抽獎了', '')
                return True, embed
            else:
                embed = errEmbed('你沒有參加過這個抽獎', '')
                return False, embed

        @discord.ui.button(label='參加抽獎', style=discord.ButtonStyle.green, custom_id='join_give_away_button')
        async def join_giveaway_callback(self, interaction: Interaction, button: discord.ui.Button):
            msg = interaction.message
            check, check_msg = await self.flow_app.checkFlowAccount(interaction.user.id)
            if check == False:
                await interaction.response.send_message(embed=check_msg, ephemeral=True)
                return
            c = await self.db.cursor()
            await c.execute('SELECT ticket FROM giveaway WHERE msg_id = ?', (msg.id,))
            ticket = await c.fetchone()
            ticket = ticket[0]
            check, check_msg = await self.ticket_flow_check(
                interaction.user.id, ticket)
            if check == False:
                await interaction.response.send_message(embed=check_msg, ephemeral=True)
                return
            check, check_msg = await self.check_if_already_in_gv(
                interaction.user.id, msg.id)
            if check == True:
                await interaction.response.send_message(embed=check_msg, ephemeral=True)
                return
            await c.execute('SELECT role_id FROM giveaway WHERE msg_id = ?', (msg.id,))
            role_id = await c.fetchone()
            role_id = role_id[0]
            r = interaction.guild.get_role(role_id)
            if r is not None and r not in interaction.user.roles:
                await interaction.response.send_message(embed=errEmbed(
                    '非常抱歉', f'你不是{r.mention}的一員, 不能參加這個抽獎'), ephemeral=True)
                return
            await self.join_giveaway(interaction.user.id, ticket, msg.id)
            await interaction.response.send_message(embed=defaultEmbed(f'flow幣 **-{ticket}**').set_author(name='成功參加抽獎'), ephemeral=True)
            await self.update_gv_msg(msg.id, interaction)
            await self.check_gv_finish(msg.id, interaction)

        @discord.ui.button(label='退出抽獎', style=discord.ButtonStyle.grey, custom_id='leave_giveaway_button')
        async def leave_giveaway_callback(self, interaction: Interaction, button: discord.ui.Button):
            msg = interaction.message
            c = await self.db.cursor()
            await c.execute('SELECT ticket FROM giveaway WHERE msg_id = ?', (msg.id,))
            ticket = await c.fetchone()
            check, check_msg = await self.check_if_already_in_gv(
                interaction.user.id, msg.id)
            if check == False:
                await interaction.response.send_message(embed=check_msg, ephemeral=True)
                return
            await self.join_giveaway(interaction.user.id, -int(ticket[0]), msg.id)
            await interaction.response.send_message(embed=defaultEmbed(message=f'你的flow幣 {-int(ticket[0])}').set_author(name='成功退出抽獎'), ephemeral=True)
            await self.update_gv_msg(msg.id, interaction)

    class GiveawayDropdownView(DefaultView):
        def __init__(self, giveaways: dict, db: aiosqlite.Connection):
            super().__init__(timeout=None)
            self.add_item(GiveAwayCog.GiveawayDropdown(giveaways, db))

    class GiveawayDropdown(Select):
        def __init__(self, gv_dict: dict, db: aiosqlite.Connection):
            self.db = db
            options = []
            if not bool(gv_dict):
                super().__init__(placeholder='目前沒有進行中的抽獎', min_values=1, max_values=1,
                                 options=[SelectOption(label='disabled')], disabled=True)
            else:
                for msg_id, prize_name in gv_dict.items():
                    options.append(SelectOption(
                        label=prize_name, value=msg_id))
                super().__init__(placeholder='選擇要結束的抽獎', min_values=1, max_values=1, options=options)

        async def callback(self, i: Interaction):
            self.view.value = self.values[0]
            await i.response.defer()
            self.view.stop()

    @app_commands.command(name='endgiveaway結束抽獎', description='強制結束抽獎並選出得獎者')
    @app_commands.checks.has_role('小雪團隊')
    async def end_giveaway(self, i: Interaction):
        c: aiosqlite.Cursor = await self.bot.db.cursor()
        await c.execute('SELECT msg_id, prize_name FROM giveaway')
        giveaways = await c.fetchall()
        giveaway_dict = {}
        for index, tuple in enumerate(giveaways):
            giveaway_dict[tuple[0]] = tuple[1]
        view = self.GiveawayDropdownView(giveaway_dict, self.bot.db)
        await i.response.send_message(view=view, ephemeral=True)
        await view.wait()
        c = await self.bot.db.cursor()
        await c.execute('SELECT * FROM giveaway_members WHERE msg_id = ?', (view.value,))
        members = await c.fetchone()
        if members is None:
            await i.followup.send(embed=defaultEmbed('🥲 強制結束失敗', '還沒有人參加過這個抽獎'), ephemeral=True)
            return
        await c.execute('SELECT goal FROM giveaway WHERE msg_id = ?', (int(view.value),))
        goal = await c.fetchone()
        goal = goal[0]
        await c.execute('UPDATE giveaway SET current = ? WHERE msg_id = ?', (goal, int(view.value)))
        await self.bot.db.commit()
        await self.GiveAwayView.check_gv_finish(self, view.value, i)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GiveAwayCog(bot))
