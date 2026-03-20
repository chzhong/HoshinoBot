from hoshino import R, Service, util

sv = Service("antiqks", help_="识破骑空士的阴谋")

qksimg = R.img("antiqks.jpg").cqcode


@sv.on_keyword("granbluefantasy.jp")
async def qks_keyword(bot, ev):
    msg = f"骑空士爪巴\n{qksimg}"
    await bot.send(ev, msg, at_sender=True)
    await util.silence(ev, 60)
