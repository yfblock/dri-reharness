# 成功快照: reharness edu 端到端 (2026-07-10)

opencode 从 reharness 提取的 .ris/.dspec/.bind/.facts 合成 Linux PCI 驱动
`examples/edu/edu_drv.c`,
在 ~/Code/linux (7.1.0-rc7) 编译为模块, 在 qemu-system-x86_64 -device edu 上运行通过。

QEMU 结果:
  edu_drv 0000:00:04.0: edu id: 0x010000ed
  edu_drv 0000:00:04.0: edu probed (irq 11)
  /dev/edu_drv 注册; rmmod 干净; 无 oops

复现: ./run.sh edu-e2e   (全流程) 或 ./run.sh edu-e2e 1 (跳过合成用本快照)
证据: research/history/e2e_success_log.txt, research/history/qemu_edu_success_log.txt
