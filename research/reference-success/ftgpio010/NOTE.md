# 真实驱动 gpio-ftgpio010 翻译+运行成功 (2026-07-10)

真实上游驱动 drivers/gpio/gpio-ftgpio010.c (Faraday GPIO, platform_driver + gpio_chip)。
reharness 提取 .ris → opencode 合成 ftgpio010_gpio.c → ~/Code/linux(7.1.0-rc7) 编译 →
qemu-system-x86_64 + device-registrar(platform 设备 ftgpio010-gpio, MMIO@0xF0000000) 运行。

QEMU 结果: gpiochip0 注册成功 (probe 返回 0, RIS init 写入执行), rmmod 干净, 无 oops。
复现: bash qemu_platform.sh ftgpio010_gpio ftgpio010-gpio 90
证据: history/qemu_ftgpio010_success_log.txt
