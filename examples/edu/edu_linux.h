#ifndef REHARNESS_EDU_LINUX_H
#define REHARNESS_EDU_LINUX_H

// Auto-generated deterministic Linux driver for edu (reharness)
// SPDX-License-Identifier: GPL-2.0
#include <linux/module.h>
#include <linux/device.h>
#include <linux/io.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/interrupt.h>
#include <linux/bits.h>
#include <linux/pci.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>


#ifndef IO_ID
#define IO_ID	0x0
#endif
#ifndef IO_IRQ_STATUS
#define IO_IRQ_STATUS	0x24
#endif
#ifndef IO_IRQ_ACK
#define IO_IRQ_ACK	0x64
#endif
#ifndef EDU_VENDOR_ID
#define EDU_VENDOR_ID	0x1234
#endif
#ifndef EDU_DEVICE_ID
#define EDU_DEVICE_ID	0x11e8
#endif
#ifndef IO_DMA_SRC
#define IO_DMA_SRC	0x80
#endif
#ifndef IO_DMA_DST
#define IO_DMA_DST	0x88
#endif
#ifndef IO_DMA_CNT
#define IO_DMA_CNT	0x90
#endif
#ifndef IO_DMA_CMD
#define IO_DMA_CMD	0x98
#endif
#ifndef DMA_BASE
#define DMA_BASE	0x40000u
#endif
#ifndef DMA_CMD
#define DMA_CMD	0x1u
#endif
#ifndef DMA_IRQ
#define DMA_IRQ	0x4u
#endif
#ifndef IO_APIC_DEFAULT_PHYS_BASE
#define IO_APIC_DEFAULT_PHYS_BASE	0xfec00000
#endif
#ifndef IO_APIC_SLOT_SIZE
#define IO_APIC_SLOT_SIZE	0x400
#endif
#ifndef IO_BITMAP_BITS
#define IO_BITMAP_BITS	0x10000
#endif
#ifndef IO_INTEGRITY_CHK_APPTAG
#define IO_INTEGRITY_CHK_APPTAG	0x4
#endif
#ifndef IO_INTEGRITY_CHK_GUARD
#define IO_INTEGRITY_CHK_GUARD	0x1
#endif
#ifndef IO_INTEGRITY_CHK_REFTAG
#define IO_INTEGRITY_CHK_REFTAG	0x2
#endif
#ifndef IO_SPACE_LIMIT
#define IO_SPACE_LIMIT	0xffff
#endif

struct edu_priv {
	struct device *dev;
	void __iomem *base;
	struct pci_dev *pdev;
	struct miscdevice misc;
};

#endif /* REHARNESS_EDU_LINUX_H */
