import time

import numpy as np

from module.automation import auto
from module.logger import log
from module.notification.notification import NotificationLevel
from tasks.base.base import Base
from tasks.base.task_steps import optional_reward
from .rewardtemplate import RewardTemplate


RECEIVE_CROP = (316 / 1920, 942 / 1080, 250 / 1920, 76 / 1080)


class Mail(RewardTemplate):
    def run(self):
        button = auto.find_element("./assets/images/zh_CN/reward/mail/receive_all.png", "image", 0.8,
                                   crop=RECEIVE_CROP, max_retries=4, retry_delay=0.3)
        if not button:
            button = auto.find_element("全部领取", "text", crop=RECEIVE_CROP, max_retries=3, retry_delay=0.3)
        if not button:
            button = auto.find_element("全部领取", "text")
        if not button:
            if auto.find_element(("暂无邮件", "没有邮件"), "text", include=True,
                                 take_screenshot=False, need_ocr=False):
                log.info("邮箱暂无可领取附件")
                return False
            raise RuntimeError("未确认邮箱可领附件状态")

        # 灰色按钮也可能匹配模板，使用定位按钮的同一帧判定是否可领。
        left, top, *_ = auto.screenshot_pos
        scale = auto.screenshot_scale_factor or 1
        (x1, y1), (x2, y2) = button
        pixels = np.asarray(auto.screenshot.convert("RGB").crop((
            round((x1 - left) * scale), round((y1 - top) * scale),
            round((x2 - left) * scale), round((y2 - top) * scale),
        )))
        if not pixels.size:
            raise RuntimeError("未确认邮箱的全部领取按钮状态")
        # 置灰按钮的底色随主界面变化，浅灰字形只占 OCR 框的一小部分。
        brightest = pixels.max(axis=-1)
        darkest = pixels.min(axis=-1)
        if ((darkest >= 145) & (brightest - darkest <= 35)).mean() >= 0.10:
            log.info("邮箱暂无可领取附件")
            return False
        red, green, blue = np.moveaxis(pixels, -1, 0)
        if ((red > 180) & (green > 125) & (blue < 155)).mean() < 0.25:
            raise RuntimeError("未确认邮箱的全部领取按钮状态")
        if not auto.click_element_with_pos(button):
            raise RuntimeError("无法点击邮箱的全部领取按钮")
        time.sleep(2)
        with optional_reward("邮件奖励通知"):
            Base.send_notification_with_screenshot("邮件奖励已领取", level=NotificationLevel.ALL)
        with optional_reward("关闭邮件奖励弹窗"):
            auto.click_element("./assets/images/zh_CN/base/click_close.png", "image", 0.8, max_retries=10)
        return True
