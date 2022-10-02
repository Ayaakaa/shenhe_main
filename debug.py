import traceback

from discord import ButtonStyle, Interaction, HTTPException
from discord.ui import Button, View, button

from utility.utils import error_embed


class DebugView(View):
    def __init__(self, traceback):
        self.tb = traceback
        super().__init__(timeout=None)

    @button(label='顯示除錯用訊息', style=ButtonStyle.gray)
    async def show_debug_msg(self, i: Interaction, button: Button):
        try:
            await i.response.send_message(embed=error_embed(f'除錯用訊息', f'```py\n{self.tb}\n```'), ephemeral=True)
        except HTTPException:
            await i.response.send_message(content='錯誤訊息過長, 已 print 在 console 裡', ephemeral=True)
            print(self.tb)


class DefaultView(View):
    async def on_error(self, i: Interaction, e: Exception, item) -> None:
        seria = i.client.get_user(410036441129943050)
        view = DebugView(traceback.format_exc())
        embed = error_embed(
            f'未知錯誤', f'```py\n{e}\n```\n```{item}\n```')
        await i.channel.send(content=f'{seria.mention} 系統已將錯誤回報給小雪, 請耐心等待修復', embed=embed, view=view)