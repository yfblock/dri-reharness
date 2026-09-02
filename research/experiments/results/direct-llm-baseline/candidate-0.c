// SPDX-License-Identifier: GPL-2.0-only
/*
 * Host-runnable test harness for the Designware SPI core driver.
 * Translates the kernel driver to a standalone C test.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>
#include <assert.h>
#include <limits.h>

/* ===== Kernel compatibility shims ===== */
#define u8      uint8_t
#define u16     uint16_t
#define u32     uint32_t
#define s32     int32_t
#define u64     uint64_t
#define s64     int64_t
#define __iomem
#define BITS_PER_BYTE 8
#define NSEC_PER_SEC  1000000000ULL
#define NSEC_PER_USEC 1000ULL
#define USHRT_MAX     0xFFFF
#define EIO           5
#define ENOMEM        12
#define EINVAL        22
#define ENOTCONN       107
#define EPROBE_DEFER  517
#define IRQ_NOTCONNECTED (-1)
#define BIT(n)    (1U << (n))
#define GENMASK(h, l) (((1U << ((h) - (l) + 1)) - 1) << (l))
#define FIELD_PREP(mask, val)  (((u32)(val) << (__builtin_ctz(mask))) & (mask))
#define FIELD_GET(mask, val)   (((u32)(val) & (mask)) >> __builtin_ctz(mask))
#define __bf_shf(mask)         (__builtin_ctz(mask))
#define DIV_ROUND_UP(n, d)     (((n) + (d) - 1) / (d))
#define DIV_ROUND_CLOSEST(x, d) (((x) + (d)/2) / (d))
#define min(a, b)        ((a) < (b) ? (a) : (b))
#define min_t(t, a, b)   ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define min3(a, b, c)    min(min((a), (b)), (c))
#define max(a, b)        ((a) > (b) ? (a) : (b))
#define clamp(val, lo, hi) ((val) < (lo) ? (lo) : ((val) > (hi) ? (hi) : (val)))
#define clamp_val(val, lo, hi) clamp(val, lo, hi)
#define hweight16(x) __builtin_popcount((unsigned int)(x))
#define SZ_4K 4096

#define IRQ_NONE    0
#define IRQ_HANDLED 1
#define IRQF_SHARED 0

#define SPI_CPOL    BIT(0)
#define SPI_CPHA    BIT(1)
#define SPI_CS_HIGH BIT(2)
#define SPI_LOOP    BIT(3)
#define SPI_MODE_0  0
#define SPI_MODE_3  (SPI_CPOL | SPI_CPHA)

#define SPI_DELAY_UNIT_USECS 1
#define SPI_DELAY_UNIT_NSECS 2
#define SPI_DELAY_UNIT_SCK   3

#define SPI_MEM_DATA_OUT 1
#define SPI_MEM_DATA_IN  2

#define SPI_CONTROLLER_GPIO_SS  BIT(0)
#define SPI_CONTROLLER_MUST_TX  BIT(1)

#define IRQF_SHARED 0

static inline u32 min3_u32(u32 a, u32 b, u32 c) { u32 m = a < b ? a : b; return m < c ? m : c; }

/* Host primitives */
uint32_t harness_read32(uintptr_t addr);
void     harness_write32(uint32_t value, uintptr_t addr);
uint8_t  harness_read8(uintptr_t addr);
void     harness_write8(uint8_t value, uintptr_t addr);
uint16_t harness_read16(uintptr_t addr);
void     harness_write16(uint16_t value, uintptr_t addr);

static inline void __raw_readl_dummy(void) {}
#define __raw_readl(addr)        (harness_read32((uintptr_t)(addr)))
#define __raw_writel(val, addr)  (harness_write32((u32)(val), (uintptr_t)(addr)))
#define readl_relaxed(addr)     (harness_read32((uintptr_t)(addr)))
#define writel_relaxed(val, addr) (harness_write32((u32)(val), (uintptr_t)(addr)))
#define readw_relaxed(addr)     (harness_read16((uintptr_t)(addr)))
#define writew_relaxed(val, addr) (harness_write16((u16)(val), (uintptr_t)(addr)))
#define __raw_readw(addr)      (harness_read16((uintptr_t)(addr)))

/* ===== Register definitions (from spi-dw.h) ===== */
#define DW_PSSI_ID       0
#define DW_HSSI_ID       1
#define DW_HSSI_102A     0x3130322a

#define DW_SPI_CAP_CS_OVERRIDE  BIT(0)
#define DW_SPI_CAP_DFS32        BIT(1)

#define DW_SPI_CTRLR0           0x00
#define DW_SPI_CTRLR1           0x04
#define DW_SPI_SSIENR           0x08
#define DW_SPI_MWCR             0x0c
#define DW_SPI_SER              0x10
#define DW_SPI_BAUDR            0x14
#define DW_SPI_TXFTLR           0x18
#define DW_SPI_RXFTLR           0x1c
#define DW_SPI_TXFLR            0x20
#define DW_SPI_RXFLR            0x24
#define DW_SPI_SR               0x28
#define DW_SPI_IMR              0x2c
#define DW_SPI_ISR              0x30
#define DW_SPI_RISR             0x34
#define DW_SPI_TXOICR           0x38
#define DW_SPI_RXOICR           0x3c
#define DW_SPI_RXUICR           0x40
#define DW_SPI_MSTICR           0x44
#define DW_SPI_ICR              0x48
#define DW_SPI_DMACR            0x4c
#define DW_SPI_DMATDLR          0x50
#define DW_SPI_DMARDLR          0x54
#define DW_SPI_IDR              0x58
#define DW_SPI_VERSION          0x5c
#define DW_SPI_DR               0x60
#define DW_SPI_RX_SAMPLE_DLY    0xf0
#define DW_SPI_CS_OVERRIDE      0xf4

#define DW_PSSI_CTRLR0_DFS_MASK       GENMASK(3, 0)
#define DW_PSSI_CTRLR0_DFS32_MASK    GENMASK(20, 16)
#define DW_PSSI_CTRLR0_FRF_MASK      GENMASK(5, 4)
#define DW_SPI_CTRLR0_FRF_MOTO_SPI   0x0
#define DW_PSSI_CTRLR0_SCPHA         BIT(6)
#define DW_PSSI_CTRLR0_SCPOL          BIT(7)
#define DW_PSSI_CTRLR0_TMOD_MASK     GENMASK(9, 8)
#define DW_PSSI_CTRLR0_SRL            BIT(11)

#define DW_HSSI_CTRLR0_DFS_MASK      GENMASK(4, 0)
#define DW_HSSI_CTRLR0_FRF_MASK      GENMASK(7, 6)
#define DW_HSSI_CTRLR0_SCPHA         BIT(8)
#define DW_HSSI_CTRLR0_SCPOL          BIT(9)
#define DW_HSSI_CTRLR0_TMOD_MASK     GENMASK(11, 10)
#define DW_HSSI_CTRLR0_SRL            BIT(13)
#define DW_HSSI_CTRLR0_MST            BIT(31)

#define DW_SPI_NDF_MASK              GENMASK(15, 0)
#define DW_SPI_SR_MASK               GENMASK(6, 0)
#define DW_SPI_SR_BUSY               BIT(0)
#define DW_SPI_SR_TF_NOT_FULL        BIT(1)
#define DW_SPI_SR_TF_EMPT            BIT(2)
#define DW_SPI_SR_RF_NOT_EMPT        BIT(3)
#define DW_SPI_SR_RF_FULL            BIT(4)
#define DW_SPI_SR_TX_ERR             BIT(5)
#define DW_SPI_SR_DCOL               BIT(6)
#define DW_SPI_INT_MASK              GENMASK(5, 0)
#define DW_SPI_INT_TXEI              BIT(0)
#define DW_SPI_INT_TXOI              BIT(1)
#define DW_SPI_INT_RXUI              BIT(2)
#define DW_SPI_INT_RXOI              BIT(3)
#define DW_SPI_INT_RXFI              BIT(4)
#define DW_SPI_INT_MSTI              BIT(5)
#define DW_SPI_DMACR_RDMAE           BIT(0)
#define DW_SPI_DMACR_TDMAE           BIT(1)

#define DW_SPI_WAIT_RETRIES  5
#define DW_SPI_BUF_SIZE      272
#define DW_SPI_GET_BYTE(_val, _idx) (((_val) >> (BITS_PER_BYTE * (_idx))) & 0xff)

#define DW_SPI_CTRLR0_TMOD_TR        0x0
#define DW_SPI_CTRLR0_TMOD_TO        0x1
#define DW_SPI_CTRLR0_TMOD_RO        0x2
#define DW_SPI_CTRLR0_TMOD_EPROMREAD 0x3

/* ===== Linux types ===== */
struct device { char name[64]; };
struct spi_controller {
    struct device dev;
    int bus_num;
    u32 num_chipselect;
    u32 mode_bits;
    u32 max_speed_hz;
    u32 flags;
    u8  bits_per_word_mask_lo;
    u8  bits_per_word_mask_hi;
    bool auto_runtime_pm;
    bool use_gpio_descriptors;
    void *priv;
    int  irq;
    struct spi_message *cur_msg;
    int (*setup)(struct spi_device *spi);
    void (*cleanup)(struct spi_device *spi);
    int (*transfer_one)(struct spi_controller *ctlr, struct spi_device *spi,
                        struct spi_transfer *transfer);
    void (*handle_err)(struct spi_controller *ctlr, struct spi_message *msg);
    int (*target_abort)(struct spi_controller *ctlr);
    void (*set_cs)(struct spi_device *spi, bool enable);
    struct spi_controller_mem_ops *mem_ops;
    struct spi_controller_mem_caps *mem_caps;
};
typedef struct spi_controller spi_controller;

static inline void spi_controller_set_devdata(struct spi_controller *ctlr, void *data) { ctlr->priv = data; }
static inline void *spi_controller_get_devdata(struct spi_controller *ctlr) { return ctlr->priv; }
static inline bool spi_controller_is_target(struct spi_controller *ctlr) { return false; }

struct spi_device {
    struct spi_controller *controller;
    u32 mode;
    u8  chip_select;
    void *ctldata;
};

static inline u32 spi_get_chipselect(struct spi_device *spi, int n) { return spi->chip_select; }
static inline void spi_set_ctldata(struct spi_device *spi, void *data) { spi->ctldata = data; }
static inline void *spi_get_ctldata(struct spi_device *spi) { return spi->ctldata; }

struct spi_transfer {
    const void *tx_buf;
    void *rx_buf;
    unsigned int len;
    u8  bits_per_word;
    u32 speed_hz;
    u32 effective_speed_hz;
    bool dma_mapped;
};

struct spi_message {
    int status;
};

struct spi_delay {
    u16 value;
    u8  unit;
};
static inline int spi_delay_exec(struct spi_delay *d, struct spi_transfer *t) { (void)d; (void)t; return 0; }

struct spi_mem_op {
    struct { u8 opcode; u8 nbytes; u8 buswidth; } cmd;
    struct { u32 val; u8 nbytes; u8 buswidth; } addr;
    struct { u8 nbytes; u8 buswidth; } dummy;
    struct {
        u8  nbytes;
        u8  buswidth;
        u8  dir;
        union { void *out; void *in; } buf;
    } data;
    u32 max_freq;
};

struct spi_mem {
    struct spi_device *spi;
};

struct spi_controller_mem_ops {
    int  (*adjust_op_size)(struct spi_mem *mem, struct spi_mem_op *op);
    bool (*supports_op)(struct spi_mem *mem, const struct spi_mem_op *op);
    int  (*exec_op)(struct spi_mem *mem, const struct spi_mem_op *op);
};
struct spi_controller_mem_caps { bool per_op_freq; };
static inline bool spi_mem_default_supports_op(struct spi_mem *mem, const struct spi_mem_op *op) {
    (void)mem; (void)op; return true;
}
static inline bool spi_xfer_is_dma_mapped(struct spi_controller *ctlr, struct spi_device *spi, struct spi_transfer *t) {
    (void)ctlr; (void)spi; return t->dma_mapped;
}
static inline u8 spi_bpw_to_bytes(u8 bpw) { return (bpw + 7) / 8; }

struct dw_spi_dma_ops {
    int  (*dma_init)(struct device *dev, struct dw_spi *dws);
    void (*dma_exit)(struct dw_spi *dws);
    int  (*dma_setup)(struct dw_spi *dws, struct spi_transfer *xfer);
    bool (*can_dma)(struct spi_controller *ctlr, struct spi_device *spi, struct spi_transfer *xfer);
    int  (*dma_transfer)(struct dw_spi *dws, struct spi_transfer *xfer);
    void (*dma_stop)(struct dw_spi *dws);
};

/* Stub dev_* */
static void dev_err(struct device *dev, const char *fmt, ...) { (void)dev; va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); fprintf(stderr, "\n"); }
static void dev_warn(struct device *dev, const char *fmt, ...) { (void)dev; va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); fprintf(stderr, "\n"); }
static void dev_dbg(struct device *dev, const char *fmt, ...) { (void)dev; va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); fprintf(stderr, "\n"); }
static int dev_err_probe(struct device *dev, int err, const char *fmt, ...) { (void)dev; va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); fprintf(stderr, "\n"); return err; }
static const char *dev_name(struct device *dev) { return dev->name; }
static bool device_property_read_bool(struct device *dev, const char *p) { (void)dev; (void)p; return false; }
static int device_property_read_u32(struct device *dev, const char *p, u32 *v) { (void)dev; (void)p; if (v) *v = 0; return -ENXIO; }

static void local_irq_save(unsigned long f) { (void)f; }
static void local_irq_restore(unsigned long f) { (void)f; }
static void preempt_disable(void) {}
static void preempt_enable(void) {}
static void smp_mb(void) {}

static int request_irq(int irq, void *handler, int flags, const char *name, void *d) { (void)irq; (void)handler; (void)flags; (void)name; (void)d; return 0; }
static void free_irq(int irq, void *d) { (void)irq; (void)d; }
static void spi_finalize_current_transfer(struct spi_controller *ctlr) { (void)ctlr; }
static int spi_controller_suspend(struct spi_controller *c) { (void)c; return 0; }
static int spi_controller_resume(struct spi_controller *c) { (void)c; return 0; }
static void spi_unregister_controller(struct spi_controller *c) { (void)c; }
static struct spi_controller *spi_alloc_host(struct device *dev, int extra) {
    (void)dev; (void)extra;
    struct spi_controller *c = calloc(1, sizeof(*c));
    return c;
}
static struct spi_controller *spi_alloc_target(struct device *dev, int extra) {
    (void)dev; (void)extra;
    struct spi_controller *c = calloc(1, sizeof(*c));
    return c;
}
static void spi_controller_put(struct spi_controller *c) { (void)c; }
static int spi_register_controller(struct spi_controller *c) { (void)c; return 0; }

typedef int irqreturn_t;
typedef int  (*transfer_handler_t)(struct dw_spi *dws);

/* ===== struct dw_spi ===== */
struct dw_spi {
    struct spi_controller *ctlr;
    u32   ip;
    u32   ver;
    u32   caps;
    void *regs;
    unsigned long paddr;
    int   irq;
    u32   fifo_len;
    unsigned int dfs_offset;
    u32   max_mem_freq;
    u32   max_freq;
    u32   reg_io_width;
    u32   num_cs;
    u16   bus_num;
    void (*set_cs)(struct spi_device *spi, bool enable);
    void *tx;
    unsigned int tx_len;
    void *rx;
    unsigned int rx_len;
    u8   buf[DW_SPI_BUF_SIZE];
    int  dma_mapped;
    u8   n_bytes;
    transfer_handler_t transfer_handler;
    u32  current_freq;
    u32  cur_rx_sample_dly;
    u32  def_rx_sample_dly_ns;
    struct spi_controller_mem_ops mem_ops;
    struct dw_spi_dma_ops *dma_ops;
    u32  dma_addr;
};

struct dw_spi_chip_data {
    u32 cr0;
    u32 rx_sample_dly;
};

/* ===== MMIO Device Model ===== */
#define MMIO_SIZE     0x1000
#define FIFO_DEPTH    32
#define RX_FIFO_DEPTH 32

struct dw_spi_hw_model {
    uint32_t regs[MMIO_SIZE / 4];
    uint8_t  byte_regs[MMIO_SIZE];
    struct {
        uint32_t data[FIFO_DEPTH];
        unsigned head, tail, count;
    } tx_fifo;
    struct {
        uint32_t data[RX_FIFO_DEPTH];
        unsigned head, tail, count;
    } rx_fifo;
    int ssi_enabled;
    int cs_active;
    bool ctrlr0_written;
    uint32_t ctrlr0_val;
    uint32_t ctrlr1_val;
    uint8_t  spi_flash[8192];
    int  flash_initialized;
    int  flash_addr;
    int  flash_state;
    int  flash_bytes_left;
    int  flash_read_pos;
    int  flash_addr_bytes_seen;
    int  flash_addr_expected;
    bool flash_addr_set;
    int  overflow_count;
};

static struct dw_spi_hw_model hw_model;
static struct dw_spi *g_dws;

static void spi_flash_init(struct dw_spi_hw_model *m) {
    memset(m->spi_flash, 0xFF, sizeof(m->spi_flash));
    /* JEDEC ID: manufacturer 0x20, type 0x20, capacity 0x15 (2Mbit) */
    m->spi_flash[0] = 0x20;
    m->spi_flash[1] = 0x20;
    m->spi_flash[2] = 0x15;
    /* 256 bytes at 0x100 */
    for (int i = 0; i < 256; i++)
        m->spi_flash[0x100 + i] = (uint8_t)(i ^ 0xAA);
    /* 64 bytes at 0x200 */
    for (int i = 0; i < 64; i++)
        m->spi_flash[0x200 + i] = (uint8_t)(0x55 ^ i);
    m->flash_initialized = 1;
    m->flash_state = 0;
    m->flash_addr_set = false;
    m->flash_addr_bytes_seen = 0;
}

static void spi_flash_handle_tx(struct dw_spi_hw_model *m, uint32_t val) {
    if (m->flash_state == 0) {
        uint8_t cmd = val & 0xFF;
        switch (cmd) {
        case 0x9F: /* JEDEC ID */
            m->flash_state = 1;
            m->flash_read_pos = 0;
            m->flash_bytes_left = 3;
            break;
        case 0x03: /* Read data */
            m->flash_state = 2;
            m->flash_addr_bytes_seen = 0;
            m->flash_addr_expected = 3;
            m->flash_addr_set = false;
            break;
        default:
            m->flash_state = 99;
            break;
        }
    } else if (m->flash_state == 2 && !m->flash_addr_set) {
        m->flash_addr = (m->flash_addr << 8) | (val & 0xFF);
        if (++m->flash_addr_bytes_seen >= m->flash_addr_expected) {
            m->flash_addr_set = true;
            m->flash_read_pos = m->flash_addr;
            m->flash_bytes_left = 64;
            m->flash_state = 3;
        }
    }
}

static uint32_t spi_flash_handle_rx(struct dw_spi_hw_model *m) {
    if (m->flash_state == 1 && m->flash_bytes_left > 0) {
        uint8_t b = m->spi_flash[m->flash_read_pos++];
        if (--m->flash_bytes_left == 0) m->flash_state = 0;
        return b;
    } else if ((m->flash_state == 3) && m->flash_bytes_left > 0) {
        if ((unsigned)m->flash_read_pos < sizeof(m->spi_flash)) {
            uint8_t b = m->spi_flash[m->flash_read_pos++];
            if (--m->flash_bytes_left == 0) m->flash_state = 0;
            return b;
        }
        m->flash_bytes_left--;
        if (m->flash_bytes_left == 0) m->flash_state = 0;
        return 0xFF;
    }
    return 0xFF;
}

static void hw_fifo_transfer_tick(struct dw_spi_hw_model *m) {
    if (!m->ssi_enabled || !m->cs_active) return;
    uint32_t ctrlr0 = m->regs[DW_SPI_CTRLR0 / 4];
    uint32_t tmode;
    if (g_dws && g_dws->ip == DW_PSSI_ID)
        tmode = FIELD_GET(DW_PSSI_CTRLR0_TMOD_MASK, ctrlr0);
    else
        tmode = FIELD_GET(DW_HSSI_CTRLR0_TMOD_MASK, ctrlr0);

    /* Move up to 8 words from TX FIFO to RX FIFO */
    for (int i = 0; i < 8; i++) {
        if (m->tx_fifo.count == 0) break;
        if (m->rx_fifo.count >= RX_FIFO_DEPTH) { m->overflow_count++; break; }
        uint32_t val = m->tx_fifo.data[m->tx_fifo.head];
        m->tx_fifo.head = (m->tx_fifo.head + 1) % FIFO_DEPTH;
        m->tx_fifo.count--;
        spi_flash_handle_tx(m, val);
        uint32_t rx_val = (tmode == DW_SPI_CTRLR0_TMOD_TO) ? 0xFF : spi_flash_handle_rx(m);
        m->rx_fifo.data[m->rx_fifo.tail] = rx_val;
        m->rx_fifo.tail = (m->rx_fifo.tail + 1) % RX_FIFO_DEPTH;
        m->rx_fifo.count++;
    }

    /* Update ISR based on FIFO levels */
    uint32_t txftlr = m->regs[DW_SPI_TXFTLR / 4];
    uint32_t rxftlr = m->regs[DW_SPI_RXFTLR / 4];
    uint32_t isr = 0;
    if (m->tx_fifo.count < txftlr) isr |= DW_SPI_INT_TXEI;
    if (m->rx_fifo.count > rxftlr) isr |= DW_SPI_INT_RXFI;
    m->regs[DW_SPI_ISR / 4] = isr;
    m->regs[DW_SPI_RISR / 4] = isr;
    m->regs[DW_SPI_RXFLR / 4] = m->rx_fifo.count;
    m->regs[DW_SPI_TXFLR / 4] = m->tx_fifo.count;
    uint32_t sr = DW_SPI_SR_TF_EMPT;
    if (m->tx_fifo.count > 0) sr &= ~DW_SPI_SR_TF_EMPT;
    if (m->tx_fifo.count < FIFO_DEPTH) sr |= DW_SPI_SR_TF_NOT_FULL;
    if (m->rx_fifo.count > 0) sr |= DW_SPI_SR_RF_NOT_EMPT;
    if (m->rx_fifo.count >= RX_FIFO_DEPTH) sr |= DW_SPI_SR_RF_FULL;
    if (m->ssi_enabled && m->cs_active) sr |= DW_SPI_SR_BUSY;
    m->regs[DW_SPI_SR / 4] = sr;
}

static void hw_model_write32(struct dw_spi_hw_model *m, uint32_t addr, uint32_t val) {
    if (addr < MMIO_SIZE)
        m->regs[addr / 4] = val;
    switch (addr) {
    case DW_SPI_SSIENR:
        m->ssi_enabled = (val & 1);
        if (!m->ssi_enabled) {
            m->tx_fifo.count = m->tx_fifo.head = m->tx_fifo.tail = 0;
            m->rx_fifo.count = m->rx_fifo.head = m->rx_fifo.tail = 0;
            m->regs[DW_SPI_TXFLR / 4] = 0;
            m->regs[DW_SPI_RXFLR / 4] = 0;
            m->regs[DW_SPI_ISR / 4] = 0;
            m->regs[DW_SPI_RISR / 4] = 0;
            m->cs_active = 0;
        }
        break;
    case DW_SPI_SER:
        m->cs_active = (val != 0);
        break;
    case DW_SPI_CTRLR0:
        m->ctrlr0_val = val;
        m->ctrlr0_written = true;
        break;
    case DW_SPI_CTRLR1:
        m->ctrlr1_val = val;
        break;
    case DW_SPI_TXFTLR:
        m->regs[DW_SPI_TXFTLR / 4] = val;
        break;
    case DW_SPI_RXFTLR:
        m->regs[DW_SPI_RXFTLR / 4] = val;
        break;
    case DW_SPI_ICR:
        m->regs[DW_SPI_ISR / 4] = 0;
        m->regs[DW_SPI_RISR / 4] = 0;
        m->regs[DW_SPI_TXOICR / 4] = 0;
        m->regs[DW_SPI_RXOICR / 4] = 0;
        m->regs[DW_SPI_RXUICR / 4] = 0;
        break;
    case DW_SPI_DR:
        if (m->ssi_enabled && m->cs_active) {
            if (m->tx_fifo.count < FIFO_DEPTH) {
                m->tx_fifo.data[m->tx_fifo.tail] = val;
                m->tx_fifo.tail = (m->tx_fifo.tail + 1) % FIFO_DEPTH;
                m->tx_fifo.count++;
            }
        }
        hw_fifo_transfer_tick(m);
        break;
    }
}

static uint32_t hw_model_read32(struct dw_spi_hw_model *m, uint32_t addr) {
    if (addr >= MMIO_SIZE) return 0;
    switch (addr) {
    case DW_SPI_ICR:
        m->regs[DW_SPI_ISR / 4] = 0;
        break;
    case DW_SPI_SR:
        hw_fifo_transfer_tick(m);
        break;
    case DW_SPI_TXFLR:
        hw_fifo_transfer_tick(m);
        break;
    case DW_SPI_RXFLR:
        hw_fifo_transfer_tick(m);
        break;
    case DW_SPI_ISR:
        hw_fifo_transfer_tick(m);
        break;
    case DW_SPI_RISR:
        hw_fifo_transfer_tick(m);
        break;
    }
    return m->regs[addr / 4];
}

static void hw_model_write16(struct dw_spi_hw_model *m, uint32_t addr, uint16_t val) {
    if (addr < MMIO_SIZE) {
        uint32_t cur = m->regs[addr / 4];
        uint32_t offset = addr & 3;
        cur &= ~(0xFFFFU << (offset * 8));
        cur |= ((uint32_t)val) << (offset * 8);
        m->regs[addr / 4] = cur;
    }
    if (addr == DW_SPI_DR) hw_model_write32(m, DW_SPI_DR, val);
}

static uint16_t hw_model_read16(struct dw_spi_hw_model *m, uint32_t addr) {
    return (uint16_t)hw_model_read32(m, addr);
}

static void hw_model_write8(struct dw_spi_hw_model *m, uint32_t addr, uint8_t val) {
    if (addr < MMIO_SIZE) {
        uint32_t cur = m->regs[addr / 4];
        uint32_t offset = addr & 3;
        cur &= ~(0xFFU << (offset * 8));
        cur |= ((uint32_t)val) << (offset * 8);
        m->regs[addr / 4] = cur;
    }
    if (addr == DW_SPI_DR) hw_model_write32(m, DW_SPI_DR, val);
}

static uint8_t hw_model_read8(struct dw_spi_hw_model *m, uint32_t addr) {
    return (uint8_t)hw_model_read32(m, addr);
}

/* ===== Host primitive implementations ===== */
uint32_t harness_read32(uintptr_t addr) {
    return hw_model_read32(&hw_model, (uint32_t)addr);
}
void harness_write32(uint32_t value, uintptr_t addr) {
    hw_model_write32(&hw_model, (uint32_t)addr, value);
}
uint8_t harness_read8(uintptr_t addr) {
    return hw_model_read8(&hw_model, (uint32_t)addr);
}
void harness_write8(uint8_t value, uintptr_t addr) {
    hw_model_write8(&hw_model, (uint32_t)addr, value);
}
uint16_t harness_read16(uintptr_t addr) {
    return hw_model_read16(&hw_model, (uint32_t)addr);
}
void harness_write16(uint16_t value, uintptr_t addr) {
    hw_model_write16(&hw_model, (uint32_t)addr, value);
}

static void hw_model_init(struct dw_spi_hw_model *m) {
    memset(m, 0, sizeof(*m));
    spi_flash_init(m);
    m->regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    m->regs[DW_SPI_SER / 4] = 0xFFFF;
    m->regs[DW_SPI_TXFTLR / 4] = FIFO_DEPTH - 1;
    m->regs[DW_SPI_IDR / 4] = 0x44435741;
    m->regs[DW_SPI_SR / 4] = DW_SPI_SR_TF_EMPT;
}

/* ===== Driver inline helpers ===== */
static inline u32 dw_readl(struct dw_spi *dws, u32 offset) {
    return __raw_readl((void *)((uintptr_t)dws->regs + offset));
}
static inline void dw_writel(struct dw_spi *dws, u32 offset, u32 val) {
    __raw_writel(val, (void *)((uintptr_t)dws->regs + offset));
}
static inline u32 dw_read_io_reg(struct dw_spi *dws, u32 offset) {
    switch (dws->reg_io_width) {
    case 2: return readw_relaxed((void *)((uintptr_t)dws->regs + offset));
    case 4: default: return readl_relaxed((void *)((uintptr_t)dws->regs + offset));
    }
}
static inline void dw_write_io_reg(struct dw_spi *dws, u32 offset, u32 val) {
    switch (dws->reg_io_width) {
    case 2: writew_relaxed(val, (void *)((uintptr_t)dws->regs + offset)); break;
    case 4: default: writel_relaxed(val, (void *)((uintptr_t)dws->regs + offset)); break;
    }
}
static inline void dw_spi_enable_chip(struct dw_spi *dws, int enable) {
    dw_writel(dws, DW_SPI_SSIENR, (enable ? 1 : 0));
}
static inline void dw_spi_set_clk(struct dw_spi *dws, u16 div) {
    dw_writel(dws, DW_SPI_BAUDR, div);
}
static inline void dw_spi_mask_intr(struct dw_spi *dws, u32 mask) {
    u32 new_mask = dw_readl(dws, DW_SPI_IMR) & ~mask;
    dw_writel(dws, DW_SPI_IMR, new_mask);
}
static inline void dw_spi_umask_intr(struct dw_spi *dws, u32 mask) {
    u32 new_mask = dw_readl(dws, DW_SPI_IMR) | mask;
    dw_writel(dws, DW_SPI_IMR, new_mask);
}
static inline void dw_spi_reset_chip(struct dw_spi *dws) {
    dw_spi_enable_chip(dws, 0);
    dw_spi_mask_intr(dws, 0xff);
    dw_readl(dws, DW_SPI_ICR);
    dw_writel(dws, DW_SPI_SER, 0);
    dw_spi_enable_chip(dws, 1);
}
static inline void dw_spi_shutdown_chip(struct dw_spi *dws) {
    dw_spi_enable_chip(dws, 0);
    dw_spi_set_clk(dws, 0);
}

#define dw_spi_ip_is(_dws, _ip) ((_dws)->ip == DW_ ## _ip ## _ID)
#define __dw_spi_ver_cmp(_dws, _ip, _ver, _op) (dw_spi_ip_is(_dws, _ip) && (_dws)->ver _op DW_ ## _ip ## _ ## _ver)
#define dw_spi_ver_is(_dws, _ip, _ver) __dw_spi_ver_cmp(_dws, _ip, _ver, ==)
#define dw_spi_ver_is_ge(_dws, _ip, _ver) __dw_spi_ver_cmp(_dws, _ip, _ver, >=)

/* ===== Driver functions ===== */
void dw_spi_set_cs(struct spi_device *spi, bool enable) {
    struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
    bool cs_high = !!(spi->mode & SPI_CS_HIGH);
    if (cs_high == enable)
        dw_writel(dws, DW_SPI_SER, BIT(spi_get_chipselect(spi, 0)));
    else
        dw_writel(dws, DW_SPI_SER, 0);
}

static inline u32 dw_spi_tx_max(struct dw_spi *dws) {
    u32 tx_room, rxtx_gap;
    tx_room = dws->fifo_len - dw_readl(dws, DW_SPI_TXFLR);
    rxtx_gap = dws->fifo_len - (dws->rx_len - dws->tx_len);
    return min3_u32((u32)dws->tx_len, tx_room, rxtx_gap);
}

static inline u32 dw_spi_rx_max(struct dw_spi *dws) {
    return min_t(u32, dws->rx_len, dw_readl(dws, DW_SPI_RXFLR));
}

static void dw_writer(struct dw_spi *dws) {
    u32 max = dw_spi_tx_max(dws);
    u32 txw = 0;
    while (max--) {
        if (dws->tx) {
            if (dws->n_bytes == 1) txw = *(u8 *)(dws->tx);
            else if (dws->n_bytes == 2) txw = *(u16 *)(dws->tx);
            else txw = *(u32 *)(dws->tx);
            dws->tx += dws->n_bytes;
        }
        dw_write_io_reg(dws, DW_SPI_DR, txw);
        --dws->tx_len;
    }
}

static void dw_reader(struct dw_spi *dws) {
    u32 max = dw_spi_rx_max(dws);
    u32 rxw;
    while (max--) {
        rxw = dw_read_io_reg(dws, DW_SPI_DR);
        if (dws->rx) {
            if (dws->n_bytes == 1) *(u8 *)(dws->rx) = rxw;
            else if (dws->n_bytes == 2) *(u16 *)(dws->rx) = rxw;
            else *(u32 *)(dws->rx) = rxw;
            dws->rx += dws->n_bytes;
        }
        --dws->rx_len;
    }
}

int dw_spi_check_status(struct dw_spi *dws, bool raw) {
    u32 irq_status;
    int ret = 0;
    if (raw) irq_status = dw_readl(dws, DW_SPI_RISR);
    else irq_status = dw_readl(dws, DW_SPI_ISR);
    if (irq_status & DW_SPI_INT_RXOI) { dev_err(&dws->ctlr->dev, "RX FIFO overflow detected\n"); ret = -EIO; }
    if (irq_status & DW_SPI_INT_RXUI) { dev_err(&dws->ctlr->dev, "RX FIFO underflow detected\n"); ret = -EIO; }
    if (irq_status & DW_SPI_INT_TXOI) { dev_err(&dws->ctlr->dev, "TX FIFO overflow detected\n"); ret = -EIO; }
    if (ret) {
        dw_spi_reset_chip(dws);
        if (dws->ctlr->cur_msg) dws->ctlr->cur_msg->status = ret;
    }
    return ret;
}

static irqreturn_t dw_spi_transfer_handler(struct dw_spi *dws) {
    u16 irq_status = dw_readl(dws, DW_SPI_ISR);
    if (dw_spi_check_status(dws, false)) {
        spi_finalize_current_transfer(dws->ctlr);
        return IRQ_HANDLED;
    }
    dw_reader(dws);
    if (!dws->rx_len) {
        dw_spi_mask_intr(dws, 0xff);
        spi_finalize_current_transfer(dws->ctlr);
    } else if (dws->rx_len <= dw_readl(dws, DW_SPI_RXFTLR)) {
        dw_writel(dws, DW_SPI_RXFTLR, dws->rx_len - 1);
    }
    if (irq_status & DW_SPI_INT_TXEI) {
        dw_writer(dws);
        if (!dws->tx_len)
            dw_spi_mask_intr(dws, DW_SPI_INT_TXEI);
    }
    return IRQ_HANDLED;
}

static irqreturn_t dw_spi_irq(int irq, void *dev_id) {
    struct spi_controller *ctlr = dev_id;
    struct dw_spi *dws = spi_controller_get_devdata(ctlr);
    u16 irq_status = dw_readl(dws, DW_SPI_ISR) & DW_SPI_INT_MASK;
    if (!irq_status) return IRQ_NONE;
    if (!ctlr->cur_msg) {
        dw_spi_mask_intr(dws, 0xff);
        return IRQ_HANDLED;
    }
    return dws->transfer_handler(dws);
}

static u32 dw_spi_prepare_cr0(struct dw_spi *dws, struct spi_device *spi) {
    u32 cr0 = 0;
    if (dw_spi_ip_is(dws, PSSI)) {
        cr0 |= FIELD_PREP(DW_PSSI_CTRLR0_FRF_MASK, DW_SPI_CTRLR0_FRF_MOTO_SPI);
        if (spi->mode & SPI_CPOL) cr0 |= DW_PSSI_CTRLR0_SCPOL;
        if (spi->mode & SPI_CPHA) cr0 |= DW_PSSI_CTRLR0_SCPHA;
        if (spi->mode & SPI_LOOP)  cr0 |= DW_PSSI_CTRLR0_SRL;
    } else {
        cr0 |= FIELD_PREP(DW_HSSI_CTRLR0_FRF_MASK, DW_SPI_CTRLR0_FRF_MOTO_SPI);
        if (spi->mode & SPI_CPOL) cr0 |= DW_HSSI_CTRLR0_SCPOL;
        if (spi->mode & SPI_CPHA) cr0 |= DW_HSSI_CTRLR0_SCPHA;
        if (spi->mode & SPI_LOOP)  cr0 |= DW_HSSI_CTRLR0_SRL;
        if (dw_spi_ver_is_ge(dws, HSSI, 102A)) cr0 |= DW_HSSI_CTRLR0_MST;
    }
    return cr0;
}

void dw_spi_update_config(struct dw_spi *dws, struct spi_device *spi, struct dw_spi_cfg *cfg) {
    struct dw_spi_chip_data *chip = spi_get_ctldata(spi);
    u32 cr0 = chip->cr0;
    u32 speed_hz;
    u16 clk_div;
    cr0 |= (cfg->dfs - 1) << dws->dfs_offset;
    if (dw_spi_ip_is(dws, PSSI))
        cr0 |= FIELD_PREP(DW_PSSI_CTRLR0_TMOD_MASK, cfg->tmode);
    else
        cr0 |= FIELD_PREP(DW_HSSI_CTRLR0_TMOD_MASK, cfg->tmode);
    dw_writel(dws, DW_SPI_CTRLR0, cr0);
    if (spi_controller_is_target(dws->ctlr)) return;
    if (cfg->tmode == DW_SPI_CTRLR0_TMOD_EPROMREAD || cfg->tmode == DW_SPI_CTRLR0_TMOD_RO)
        dw_writel(dws, DW_SPI_CTRLR1, cfg->ndf ? cfg->ndf - 1 : 0);
    clk_div = (DIV_ROUND_UP(dws->max_freq, cfg->freq) + 1) & 0xfffe;
    speed_hz = dws->max_freq / clk_div;
    if (dws->current_freq != speed_hz) {
        dw_spi_set_clk(dws, clk_div);
        dws->current_freq = speed_hz;
    }
    if (dws->cur_rx_sample_dly != chip->rx_sample_dly) {
        dw_writel(dws, DW_SPI_RX_SAMPLE_DLY, chip->rx_sample_dly);
        dws->cur_rx_sample_dly = chip->rx_sample_dly;
    }
}

static void dw_spi_irq_setup(struct dw_spi *dws) {
    u16 level;
    u8 imask;
    level = min_t(unsigned int, dws->fifo_len / 2, dws->tx_len);
    dw_writel(dws, DW_SPI_TXFTLR, level);
    dw_writel(dws, DW_SPI_RXFTLR, level - 1);
    dws->transfer_handler = dw_spi_transfer_handler;
    imask = DW_SPI_INT_TXEI | DW_SPI_INT_TXOI | DW_SPI_INT_RXUI | DW_SPI_INT_RXOI | DW_SPI_INT_RXFI;
    dw_spi_umask_intr(dws, imask);
}

static int dw_spi_poll_transfer(struct dw_spi *dws, struct spi_transfer *transfer) {
    struct spi_delay delay;
    u16 nbits;
    int ret;
    delay.unit = SPI_DELAY_UNIT_SCK;
    nbits = dws->n_bytes * BITS_PER_BYTE;
    do {
        dw_writer(dws);
        delay.value = nbits * (dws->rx_len - dws->tx_len);
        spi_delay_exec(&delay, transfer);
        dw_reader(dws);
        ret = dw_spi_check_status(dws, true);
        if (ret) return ret;
    } while (dws->rx_len);
    return 0;
}

static int dw_spi_transfer_one(struct spi_controller *ctlr, struct spi_device *spi, struct spi_transfer *transfer) {
    struct dw_spi *dws = spi_controller_get_devdata(ctlr);
    struct dw_spi_cfg cfg = { .tmode = DW_SPI_CTRLR0_TMOD_TR, .dfs = transfer->bits_per_word, .freq = transfer->speed_hz };
    int ret;
    dws->dma_mapped = 0;
    dws->n_bytes = spi_bpw_to_bytes(transfer->bits_per_word);
    dws->tx = (void *)transfer->tx_buf;
    dws->tx_len = transfer->len / dws->n_bytes;
    dws->rx = transfer->rx_buf;
    dws->rx_len = dws->tx_len;
    smp_mb();
    dw_spi_enable_chip(dws, 0);
    dw_spi_update_config(dws, spi, &cfg);
    transfer->effective_speed_hz = dws->current_freq;
    dws->dma_mapped = spi_xfer_is_dma_mapped(ctlr, spi, transfer);
    dw_spi_mask_intr(dws, 0xff);
    if (dws->dma_mapped) {
        ret = dws->dma_ops->dma_setup(dws, transfer);
        if (ret) return ret;
    }
    dw_spi_enable_chip(dws, 1);
    if (dws->dma_mapped) return dws->dma_ops->dma_transfer(dws, transfer);
    else if (dws->irq == IRQ_NOTCONNECTED) return dw_spi_poll_transfer(dws, transfer);
    dw_spi_irq_setup(dws);
    return 1;
}

static inline void dw_spi_abort(struct dw_spi *ctlr_param) {
    struct dw_spi *dws = spi_controller_get_devdata(ctlr_param->ctlr);
    if (dws->dma_mapped) dws->dma_ops->dma_stop(dws);
    dw_spi_reset_chip(dws);
}
static void dw_spi_handle_err(struct spi_controller *ctlr, struct spi_message *msg) {
    (void)msg;
    struct dw_spi *dws = spi_controller_get_devdata(ctlr);
    dw_spi_reset_chip(dws);
}
static int dw_spi_target_abort(struct spi_controller *ctlr) {
    struct dw_spi *dws = spi_controller_get_devdata(ctlr);
    dw_spi_reset_chip(dws);
    return 0;
}

static int dw_spi_adjust_mem_op_size(struct spi_mem *mem, struct spi_mem_op *op) {
    if (op->data.dir == SPI_MEM_DATA_IN)
        op->data.nbytes = clamp_val(op->data.nbytes, 0, DW_SPI_NDF_MASK + 1);
    return 0;
}
static bool dw_spi_supports_mem_op(struct spi_mem *mem, const struct spi_mem_op *op) {
    if (op->data.buswidth > 1 || op->addr.buswidth > 1 || op->dummy.buswidth > 1 || op->cmd.buswidth > 1)
        return false;
    return spi_mem_default_supports_op(mem, op);
}

static int dw_spi_init_mem_buf(struct dw_spi *dws, const struct spi_mem_op *op) {
    unsigned int i, j, len;
    u8 *out;
    len = op->cmd.nbytes + op->addr.nbytes + op->dummy.nbytes;
    if (op->data.dir == SPI_MEM_DATA_OUT) len += op->data.nbytes;
    if (len <= DW_SPI_BUF_SIZE) {
        out = dws->buf;
    } else {
        out = calloc(len, 1);
        if (!out) return -ENOMEM;
    }
    for (i = 0; i < op->cmd.nbytes; ++i)
        out[i] = DW_SPI_GET_BYTE(op->cmd.opcode, op->cmd.nbytes - i - 1);
    for (j = 0; j < op->addr.nbytes; ++i, ++j)
        out[i] = DW_SPI_GET_BYTE(op->addr.val, op->addr.nbytes - j - 1);
    for (j = 0; j < op->dummy.nbytes; ++i, ++j)
        out[i] = 0x0;
    if (op->data.dir == SPI_MEM_DATA_OUT)
        memcpy(&out[i], op->data.buf.out, op->data.nbytes);
    dws->n_bytes = 1;
    dws->tx = out;
    dws->tx_len = len;
    if (op->data.dir == SPI_MEM_DATA_IN) {
        dws->rx = op->data.buf.in;
        dws->rx_len = op->data.nbytes;
    } else {
        dws->rx = NULL;
        dws->rx_len = 0;
    }
    return 0;
}

static void dw_spi_free_mem_buf(struct dw_spi *dws) {
    if (dws->tx != dws->buf) free(dws->tx);
}

static int dw_spi_write_then_read(struct dw_spi *dws, struct spi_device *spi) {
    u32 room, entries, sts;
    unsigned int len;
    u8 *buf;
    len = min(dws->fifo_len, dws->tx_len);
    buf = dws->tx;
    while (len--)
        dw_write_io_reg(dws, DW_SPI_DR, *buf++);
    len = dws->tx_len - ((void *)buf - dws->tx);
    dw_spi_set_cs(spi, false);
    while (len) {
        entries = readl_relaxed((void *)((uintptr_t)dws->regs + DW_SPI_TXFLR));
        if (!entries) { dev_err(&dws->ctlr->dev, "CS de-assertion on Tx\n"); return -EIO; }
        room = min(dws->fifo_len - entries, len);
        for (; room; --room, --len)
            dw_write_io_reg(dws, DW_SPI_DR, *buf++);
    }
    len = dws->rx_len;
    buf = dws->rx;
    while (len) {
        entries = readl_relaxed((void *)((uintptr_t)dws->regs + DW_SPI_RXFLR));
        if (!entries) {
            sts = readl_relaxed((void *)((uintptr_t)dws->regs + DW_SPI_RISR));
            if (sts & DW_SPI_INT_RXOI) { dev_err(&dws->ctlr->dev, "FIFO overflow on Rx\n"); return -EIO; }
            continue;
        }
        entries = min(entries, len);
        for (; entries; --entries, --len)
            *buf++ = dw_read_io_reg(dws, DW_SPI_DR);
    }
    return 0;
}

static inline bool dw_spi_ctlr_busy(struct dw_spi *dws) {
    return dw_readl(dws, DW_SPI_SR) & DW_SPI_SR_BUSY;
}

static int dw_spi_wait_mem_op_done(struct dw_spi *dws) {
    int retry = DW_SPI_WAIT_RETRIES;
    while (dw_spi_ctlr_busy(dws) && retry--)
        ;
    if (retry < 0) { dev_err(&dws->ctlr->dev, "Mem op hanged up\n"); return -EIO; }
    return 0;
}

static void dw_spi_stop_mem_op(struct dw_spi *dws, struct spi_device *spi) {
    dw_spi_enable_chip(dws, 0);
    dw_spi_set_cs(spi, true);
    dw_spi_enable_chip(dws, 1);
}

static int dw_spi_exec_mem_op(struct spi_mem *mem, const struct spi_mem_op *op) {
    struct dw_spi *dws = spi_controller_get_devdata(mem->spi->controller);
    struct dw_spi_cfg cfg;
    unsigned long flags;
    int ret;
    ret = dw_spi_init_mem_buf(dws, op);
    if (ret) return ret;
    cfg.dfs = 8;
    cfg.freq = clamp(op->max_freq, 0U, dws->max_mem_freq);
    if (op->data.dir == SPI_MEM_DATA_IN) {
        cfg.tmode = DW_SPI_CTRLR0_TMOD_EPROMREAD;
        cfg.ndf = op->data.nbytes;
    } else {
        cfg.tmode = DW_SPI_CTRLR0_TMOD_TO;
    }
    dw_spi_enable_chip(dws, 0);
    dw_spi_update_config(dws, mem->spi, &cfg);
    dw_spi_mask_intr(dws, 0xff);
    dw_spi_enable_chip(dws, 1);
    local_irq_save(flags);
    preempt_disable();
    ret = dw_spi_write_then_read(dws, mem->spi);
    local_irq_restore(flags);
    preempt_enable();
    if (!ret) {
        ret = dw_spi_wait_mem_op_done(dws);
        if (!ret) ret = dw_spi_check_status(dws, true);
    }
    dw_spi_stop_mem_op(dws, mem->spi);
    dw_spi_free_mem_buf(dws);
    return ret;
}

static void dw_spi_init_mem_ops(struct dw_spi *dws) {
    if (!dws->mem_ops.exec_op && !(dws->caps & DW_SPI_CAP_CS_OVERRIDE) && !dws->set_cs) {
        dws->mem_ops.adjust_op_size = dw_spi_adjust_mem_op_size;
        dws->mem_ops.supports_op = dw_spi_supports_mem_op;
        dws->mem_ops.exec_op = dw_spi_exec_mem_op;
        if (!dws->max_mem_freq) dws->max_mem_freq = dws->max_freq;
    }
}

static int dw_spi_setup(struct spi_device *spi) {
    struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
    struct dw_spi_chip_data *chip;
    chip = spi_get_ctldata(spi);
    if (!chip) {
        u32 rx_sample_dly_ns = 0;
        chip = calloc(1, sizeof(*chip));
        if (!chip) return -ENOMEM;
        spi_set_ctldata(spi, chip);
        rx_sample_dly_ns = dws->def_rx_sample_dly_ns;
        chip->rx_sample_dly = DIV_ROUND_CLOSEST(rx_sample_dly_ns, NSEC_PER_SEC / dws->max_freq);
    }
    chip->cr0 = dw_spi_prepare_cr0(dws, spi);
    return 0;
}

static void dw_spi_cleanup(struct spi_device *spi) {
    struct dw_spi_chip_data *chip = spi_get_ctldata(spi);
    free(chip);
    spi_set_ctldata(spi, NULL);
}

static const struct spi_controller_mem_caps dw_spi_mem_caps = { .per_op_freq = true };

static void dw_spi_hw_init(struct device *dev, struct dw_spi *dws) {
    dw_spi_reset_chip(dws);
    if (!dws->ver) {
        dws->ver = dw_readl(dws, DW_SPI_VERSION);
        dev_dbg(dev, "Synopsys DWC%sSSI v%c.%c%c\n",
                dw_spi_ip_is(dws, PSSI) ? " APB " : " ",
                DW_SPI_GET_BYTE(dws->ver, 3), DW_SPI_GET_BYTE(dws->ver, 2),
                DW_SPI_GET_BYTE(dws->ver, 1));
    }
    if (spi_controller_is_target(dws->ctlr)) {
        dws->num_cs = 1;
    } else {
        if (!dws->num_cs) {
            u32 ser;
            dw_writel(dws, DW_SPI_SER, 0xffff);
            ser = dw_readl(dws, DW_SPI_SER);
            dw_writel(dws, DW_SPI_SER, 0);
            dws->num_cs = hweight16(ser);
        }
    }
    if (!dws->fifo_len) {
        u32 fifo;
        for (fifo = 1; fifo < 256; fifo++) {
            dw_writel(dws, DW_SPI_TXFTLR, fifo);
            if (fifo != dw_readl(dws, DW_SPI_TXFTLR)) break;
        }
        dw_writel(dws, DW_SPI_TXFTLR, 0);
        dws->fifo_len = (fifo == 1) ? 0 : fifo;
        dev_dbg(dev, "Detected FIFO size: %u bytes\n", dws->fifo_len);
    }
    if (dw_spi_ip_is(dws, PSSI)) {
        u32 cr0, tmp = dw_readl(dws, DW_SPI_CTRLR0);
        dw_spi_enable_chip(dws, 0);
        dw_writel(dws, DW_SPI_CTRLR0, 0xffffffff);
        cr0 = dw_readl(dws, DW_SPI_CTRLR0);
        dw_writel(dws, DW_SPI_CTRLR0, tmp);
        dw_spi_enable_chip(dws, 1);
        if (!(cr0 & DW_PSSI_CTRLR0_DFS_MASK)) {
            dws->caps |= DW_SPI_CAP_DFS32;
            dws->dfs_offset = __bf_shf(DW_PSSI_CTRLR0_DFS32_MASK);
            dev_dbg(dev, "Detected 32-bits max data frame size\n");
        }
    } else {
        dws->caps |= DW_SPI_CAP_DFS32;
    }
    if (dws->caps & DW_SPI_CAP_CS_OVERRIDE)
        dw_writel(dws, DW_SPI_CS_OVERRIDE, 0xF);
}

int dw_spi_add_controller(struct device *dev, struct dw_spi *dws) {
    struct spi_controller *ctlr;
    bool target;
    int ret;
    if (!dws) return -EINVAL;
    target = device_property_read_bool(dev, "spi-slave");
    if (target) ctlr = spi_alloc_target(dev, 0);
    else ctlr = spi_alloc_host(dev, 0);
    if (!ctlr) return -ENOMEM;
    dws->ctlr = ctlr;
    dws->dma_addr = (uint32_t)(dws->paddr + DW_SPI_DR);
    spi_controller_set_devdata(ctlr, dws);
    dw_spi_hw_init(dev, dws);
    ret = request_irq(dws->irq, dw_spi_irq, IRQF_SHARED, dev_name(dev), ctlr);
    if (ret < 0 && ret != -ENOTCONN) { dev_err(dev, "can not get IRQ\n"); goto err_free_ctlr; }
    dw_spi_init_mem_ops(dws);
    ctlr->mode_bits = SPI_CPOL | SPI_CPHA;
    if (dws->caps & DW_SPI_CAP_DFS32) { ctlr->bits_per_word_mask_lo = 4; ctlr->bits_per_word_mask_hi = 32; }
    else { ctlr->bits_per_word_mask_lo = 4; ctlr->bits_per_word_mask_hi = 16; }
    ctlr->bus_num = dws->bus_num;
    ctlr->num_chipselect = dws->num_cs;
    ctlr->setup = dw_spi_setup;
    ctlr->cleanup = dw_spi_cleanup;
    ctlr->transfer_one = dw_spi_transfer_one;
    ctlr->handle_err = dw_spi_handle_err;
    ctlr->auto_runtime_pm = true;
    if (!target) {
        ctlr->use_gpio_descriptors = true;
        ctlr->mode_bits |= SPI_LOOP;
        if (dws->set_cs) ctlr->set_cs = dws->set_cs;
        else ctlr->set_cs = dw_spi_set_cs;
        if (dws->mem_ops.exec_op) {
            ctlr->mem_ops = &dws->mem_ops;
            ctlr->mem_caps = (struct spi_controller_mem_caps *)&dw_spi_mem_caps;
        }
        ctlr->max_speed_hz = dws->max_freq;
        ctlr->flags = SPI_CONTROLLER_GPIO_SS;
    } else {
        ctlr->target_abort = dw_spi_target_abort;
    }
    device_property_read_u32(dev, "rx-sample-delay-ns", &dws->def_rx_sample_dly_ns);
    ret = spi_register_controller(ctlr);
    if (ret) { dev_err_probe(dev, ret, "problem registering spi controller\n"); goto err_dma_exit; }
    return 0;
err_dma_exit:
err_free_irq:
    free_irq(dws->irq, ctlr);
err_free_ctlr:
    spi_controller_put(ctlr);
    return ret;
}

void dw_spi_remove_controller(struct dw_spi *dws) {
    spi_unregister_controller(dws->ctlr);
    dw_spi_shutdown_chip(dws);
    free_irq(dws->irq, dws->ctlr);
}

int dw_spi_suspend_controller(struct dw_spi *dws) {
    int ret = spi_controller_suspend(dws->ctlr);
    if (ret) return ret;
    dw_spi_shutdown_chip(dws);
    return 0;
}

int dw_spi_resume_controller(struct dw_spi *dws) {
    dw_spi_hw_init(&dws->ctlr->dev, dws);
    return spi_controller_resume(dws->ctlr);
}

/* ===== Test main ===== */
static int test_pass = 0, test_fail = 0;
static struct spi_controller *g_ctlr;
static struct dw_spi g_dws_struct;
static struct device g_dev;
static struct spi_device g_spi;

static void check(const char *name, bool cond) {
    if (cond) { test_pass++; printf("[PASS] %s\n", name); }
    else { test_fail++; printf("[FAIL] %s\n", name); }
}

static void test_register_access(void) {
    struct dw_spi *dws = &g_dws_struct;
    printf("\n--- Test: Register Access ---\n");
    dw_spi_reset_chip(dws);
    check("SSIENR=1 after reset", dw_readl(dws, DW_SPI_SSIENR) == 1);
    dw_writel(dws, DW_SPI_IMR, 0x3F);
    check("IMR write 0x3F", dw_readl(dws, DW_SPI_IMR) == 0x3F);
    dw_spi_mask_intr(dws, DW_SPI_INT_TXEI);
    check("mask TXEI clears bit0", (dw_readl(dws, DW_SPI_IMR) & DW_SPI_INT_TXEI) == 0);
    dw_spi_umask_intr(dws, DW_SPI_INT_TXEI);
    check("umask TXEI sets bit0", (dw_readl(dws, DW_SPI_IMR) & DW_SPI_INT_TXEI) != 0);
    dw_spi_enable_chip(dws, 0);
    check("disable: SSIENR=0", dw_readl(dws, DW_SPI_SSIENR) == 0);
    dw_spi_enable_chip(dws, 1);
    check("enable: SSIENR=1", dw_readl(dws, DW_SPI_SSIENR) == 1);
    dw_spi_set_clk(dws, 4);
    check("BAUDR write", dw_readl(dws, DW_SPI_BAUDR) == 4);
}

static void test_controller_init(void) {
    printf("\n--- Test: Controller Init ---\n");
    struct dw_spi *dws = &g_dws_struct;
    check("fifo_len detected=32", dws->fifo_len == 32);
    check("num_cs detected=16", dws->num_cs == 16);
    check("ver=read from VERSION", dws->ver == DW_HSSI_102A);
    check("CAP_DFS32 set", (dws->caps & DW_SPI_CAP_DFS32) != 0);
    check("mem_ops.exec_op set", dws->mem_ops.exec_op != NULL);
    check("ctlr->transfer_one set", g_ctlr->transfer_one != NULL);
    check("ctlr->set_cs set", g_ctlr->set_cs != NULL);
    check("ctlr->max_speed_hz", g_ctlr->max_speed_hz == dws->max_freq);
}

static void test_set_cs(void) {
    printf("\n--- Test: Set CS ---\n");
    struct dw_spi *dws = &g_dws_struct;
    g_spi.chip_select = 0;
    g_spi.mode = SPI_MODE_0;
    dw_spi_set_cs(&g_spi, true);
    check("CS active low: SER=BIT(0)", dw_readl(dws, DW_SPI_SER) == BIT(0));
    dw_spi_set_cs(&g_spi, false);
    check("CS deassert: SER=0", dw_readl(dws, DW_SPI_SER) == 0);
    g_spi.mode = SPI_CS_HIGH;
    dw_spi_set_cs(&g_spi, true);
    check("CS active high: SER=BIT(0)", dw_readl(dws, DW_SPI_SER) == BIT(0));
    dw_spi_set_cs(&g_spi, false);
    check("CS active high deassert: SER=0", dw_readl(dws, DW_SPI_SER) == 0);
    g_spi.mode = SPI_MODE_0;
}

static void test_setup(void) {
    printf("\n--- Test: Setup ---\n");
    int ret = dw_spi_setup(&g_spi);
    check("setup returns 0", ret == 0);
    struct dw_spi_chip_data *chip = spi_get_ctldata(&g_spi);
    check("chip allocated", chip != NULL);
    check("cr0 has MST bit (HSSI>=102A)", (chip->cr0 & DW_HSSI_CTRLR0_MST) != 0);
    check("cr0 FRF=MOTO_SPI",
          FIELD_GET(DW_HSSI_CTRLR0_FRF_MASK, chip->cr0) == DW_SPI_CTRLR0_FRF_MOTO_SPI);
    g_spi.mode = SPI_MODE_3;
    dw_spi_setup(&g_spi);
    chip = spi_get_ctldata(&g_spi);
    check("SPI_MODE_3 sets SCPOL+SCPHA",
          (chip->cr0 & DW_HSSI_CTRLR0_SCPOL) && (chip->cr0 & DW_HSSI_CTRLR0_SCPHA));
    g_spi.mode = SPI_LOOP;
    dw_spi_setup(&g_spi);
    chip = spi_get_ctldata(&g_spi);
    check("SPI_LOOP sets SRL", (chip->cr0 & DW_HSSI_CTRLR0_SRL) != 0);
    g_spi.mode = SPI_MODE_0;
    dw_spi_setup(&g_spi);
}

static void test_poll_transfer_8bit(void) {
    printf("\n--- Test: Poll Transfer (8-bit) ---\n");
    struct dw_spi *dws = &g_dws_struct;
    u8 tx_buf[16], rx_buf[16];
    for (int i = 0; i < 16; i++) tx_buf[i] = (u8)(0xA0 + i);
    struct spi_transfer xfer = { .tx_buf = tx_buf, .rx_buf = rx_buf, .len = 16, .bits_per_word = 8, .speed_hz = 1000000 };
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    dws->ver = DW_HSSI_102A;
    dws->fifo_len = 32; dws->num_cs = 16; dws->caps = DW_SPI_CAP_DFS32;
    spi_flash_init(&hw_model);
    int ret = dw_spi_transfer_one(g_ctlr, &g_spi, &xfer);
    check("transfer_one returns 1 (IRQ)", ret == 1);
    dw_spi_mask_intr(dws, 0xff);
    dws->irq = IRQ_NOTCONNECTED;
    ret = dw_spi_transfer_one(g_ctlr, &g_spi, &xfer);
    check("poll transfer returns 0", ret == 0);
    bool match = true;
    for (int i = 0; i < 16; i++) {
        if (rx_buf[i] != 0xFF) { match = false; break; }
    }
    check("poll rx all 0xFF", match);
    dws->irq = 42;
}

static void test_irq_transfer(void) {
    printf("\n--- Test: IRQ Transfer ---\n");
    struct dw_spi *dws = &g_dws_struct;
    u8 tx_buf[64], rx_buf[64];
    for (int i = 0; i < 64; i++) tx_buf[i] = (u8)i;
    struct spi_transfer xfer = { .tx_buf = tx_buf, .rx_buf = rx_buf, .len = 64, .bits_per_word = 8, .speed_hz = 1000000 };
    struct spi_message msg = { .status = 0 };
    g_ctlr->cur_msg = &msg;
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    dws->ver = DW_HSSI_102A; dws->fifo_len = 32; dws->num_cs = 16; dws->caps = DW_SPI_CAP_DFS32;
    spi_flash_init(&hw_model);
    int ret = dw_spi_transfer_one(g_ctlr, &g_spi, &xfer);
    check("irq setup returns 1", ret == 1);
    int max_irqs = 1000;
    while (dws->rx_len > 0 && max_irqs-- > 0) {
        uint32_t isr = dw_readl(dws, DW_SPI_ISR);
        if (isr) dw_spi_irq(42, g_ctlr);
        else hw_fifo_transfer_tick(&hw_model);
    }
    check("irq transfer completed", dws->rx_len == 0);
    bool match = true;
    for (int i = 0; i < 64; i++) {
        if (rx_buf[i] != 0xFF) { match = false; break; }
    }
    check("irq rx all 0xFF", match);
    g_ctlr->cur_msg = NULL;
}

static void test_16bit_transfer(void) {
    printf("\n--- Test: 16-bit Transfer ---\n");
    struct dw_spi *dws = &g_dws_struct;
    u16 tx_buf[8], rx_buf[8];
    for (int i = 0; i < 8; i++) tx_buf[i] = (u16)(0xBEEF + i);
    struct spi_transfer xfer = { .tx_buf = tx_buf, .rx_buf = rx_buf, .len = 16, .bits_per_word = 16, .speed_hz = 1000000 };
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    dws->ver = DW_HSSI_102A; dws->fifo_len = 32; dws->num_cs = 16; dws->caps = DW_SPI_CAP_DFS32;
    spi_flash_init(&hw_model);
    dws->irq = IRQ_NOTCONNECTED;
    int ret = dw_spi_transfer_one(g_ctlr, &g_spi, &xfer);
    check("16-bit poll transfer", ret == 0);
    check("n_bytes=2", dws->n_bytes == 2);
    dws->irq = 42;
}

static void test_mem_op_jedec(void) {
    printf("\n--- Test: SPI Mem Op (JEDEC ID) ---\n");
    struct dw_spi *dws = &g_dws_struct;
    u8 rx_buf[3] = {0};
    struct spi_mem_op op = {
        .cmd = { .opcode = 0x9F, .nbytes = 1, .buswidth = 1 },
        .addr = { .val = 0, .nbytes = 0, .buswidth = 1 },
        .dummy = { .nbytes = 0, .buswidth = 1 },
        .data = { .nbytes = 3, .buswidth = 1, .dir = SPI_MEM_DATA_IN, .buf.in = rx_buf },
        .max_freq = 40000000,
    };
    struct spi_mem mem = { .spi = &g_spi };
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    dws->ver = DW_HSSI_102A; dws->fifo_len = 32; dws->num_cs = 16; dws->caps = DW_SPI_CAP_DFS32;
    spi_flash_init(&hw_model);
    int ret = dw_spi_exec_mem_op(&mem, &op);
    check("jedec exec_op returns 0", ret == 0);
    check("rx[0]=0x20 (manuf)", rx_buf[0] == 0x20);
    check("rx[1]=0x20 (type)", rx_buf[1] == 0x20);
    check("rx[2]=0x15 (capacity)", rx_buf[2] == 0x15);
}

static void test_mem_op_read(void) {
    printf("\n--- Test: SPI Mem Op (Read Data) ---\n");
    struct dw_spi *dws = &g_dws_struct;
    u8 rx_buf[32];
    memset(rx_buf, 0, sizeof(rx_buf));
    struct spi_mem_op op = {
        .cmd = { .opcode = 0x03, .nbytes = 1, .buswidth = 1 },
        .addr = { .val = 0x100, .nbytes = 3, .buswidth = 1 },
        .dummy = { .nbytes = 0, .buswidth = 1 },
        .data = { .nbytes = 32, .buswidth = 1, .dir = SPI_MEM_DATA_IN, .buf.in = rx_buf },
        .max_freq = 40000000,
    };
    struct spi_mem mem = { .spi = &g_spi };
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    dws->ver = DW_HSSI_102A; dws->fifo_len = 32; dws->num_cs = 16; dws->caps = DW_SPI_CAP_DFS32;
    spi_flash_init(&hw_model);
    int ret = dw_spi_exec_mem_op(&mem, &op);
    check("read exec_op returns 0", ret == 0);
    bool match = true;
    for (int i = 0; i < 32; i++) {
        if (rx_buf[i] != (u8)(i ^ 0xAA)) { match = false; break; }
    }
    check("read data matches flash content", match);
    u8 rx_buf2[8];
    struct spi_mem_op op2 = {
        .cmd = { .opcode = 0x03, .nbytes = 1, .buswidth = 1 },
        .addr = { .val = 0x200, .nbytes = 3, .buswidth = 1 },
        .dummy = { .nbytes = 0, .buswidth = 1 },
        .data = { .nbytes = 8, .buswidth = 1, .dir = SPI_MEM_DATA_IN, .buf.in = rx_buf2 },
        .max_freq = 40000000,
    };
    ret = dw_spi_exec_mem_op(&mem, &op2);
    check("read at 0x200 returns 0", ret == 0);
    bool match2 = true;
    for (int i = 0; i < 8; i++) {
        if (rx_buf2[i] != (u8)(0x55 ^ i)) { match2 = false; break; }
    }
    check("read at 0x200 matches", match2);
}

static void test_mem_op_write(void) {
    printf("\n--- Test: SPI Mem Op (Write) ---\n");
    struct dw_spi *dws = &g_dws_struct;
    u8 tx_data[4] = { 0xDE, 0xAD, 0xBE, 0xEF };
    struct spi_mem_op op = {
        .cmd = { .opcode = 0x02, .nbytes = 1, .buswidth = 1 },
        .addr = { .val = 0x300, .nbytes = 3, .buswidth = 1 },
        .dummy = { .nbytes = 0, .buswidth = 1 },
        .data = { .nbytes = 4, .buswidth = 1, .dir = SPI_MEM_DATA_OUT, .buf.out = tx_data },
        .max_freq = 40000000,
    };
    struct spi_mem mem = { .spi = &g_spi };
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;
    dws->ver = DW_HSSI_102A; dws->fifo_len = 32; dws->num_cs = 16; dws->caps = DW_SPI_CAP_DFS32;
    spi_flash_init(&hw_model);
    int ret = dw_spi_exec_mem_op(&mem, &op);
    check("write exec_op returns 0", ret == 0);
}

static void test_adjust_op_size(void) {
    printf("\n--- Test: Adjust Op Size ---\n");
    struct spi_mem mem = { .spi = &g_spi };
    struct spi_mem_op op = {
        .cmd = { .opcode = 0x03, .nbytes = 1, .buswidth = 1 },
        .addr = { .val = 0, .nbytes = 3, .buswidth = 1 },
        .dummy = { .nbytes = 0, .buswidth = 1 },
        .data = { .nbytes = 0x10000, .buswidth = 1, .dir = SPI_MEM_DATA_IN, .buf.in = NULL },
        .max_freq = 40000000,
    };
    dw_spi_adjust_mem_op_size(&mem, &op);
    check("op size clamped to 0x10000", op.data.nbytes == (DW_SPI_NDF_MASK + 1));
    op.data.nbytes = 100;
    dw_spi_adjust_mem_op_size(&mem, &op);
    check("op size 100 unchanged", op.data.nbytes == 100);
    bool sup = dw_spi_supports_mem_op(&mem, &op);
    check("supports_op returns true", sup);
}

static void test_check_status(void) {
    printf("\n--- Test: Check Status ---\n");
    struct dw_spi *dws = &g_dws_struct;
    dw_spi_reset_chip(dws);
    int ret = dw_spi_check_status(dws, false);
    check("check_status clean returns 0", ret == 0);
    dw_writel(dws, DW_SPI_RISR, DW_SPI_INT_RXOI);
    ret = dw_spi_check_status(dws, true);
    check("check_status RXOI returns -EIO", ret == -EIO);
    dw_writel(dws, DW_SPI_RISR, DW_SPI_INT_TXOI);
    ret = dw_spi_check_status(dws, true);
    check("check_status TXOI returns -EIO", ret == -EIO);
}

static void test_suspend_resume(void) {
    printf("\n--- Test: Suspend/Resume ---\n");
    struct dw_spi *dws = &g_dws_struct;
    int ret = dw_spi_suspend_controller(dws);
    check("suspend returns 0", ret == 0);
    check("chip disabled after suspend", dw_readl(dws, DW_SPI_SSIENR) == 0);
    ret = dw_spi_resume_controller(dws);
    check("resume returns 0", ret == 0);
    check("chip enabled after resume", dw_readl(dws, DW_SPI_SSIENR) == 1);
}

static void test_overflow(void) {
    printf("\n--- Test: FIFO Overflow ---\n");
    struct dw_spi *dws = &g_dws_struct;
    dw_spi_reset_chip(dws);
    dw_spi_enable_chip(dws, 1);
    dw_writel(dws, DW_SPI_SER, 1);
    hw_model.tx_fifo.count = 0;
    hw_model.rx_fifo.count = RX_FIFO_DEPTH;
    for (int i = 0; i < RX_FIFO_DEPTH; i++)
        hw_model.rx_fifo.data[i] = 0xAA;
    hw_model.rx_fifo.head = 0; hw_model.rx_fifo.tail = 0;
    dw_write_io_reg(dws, DW_SPI_DR, 0x55);
    check("overflow detected", hw_model.overflow_count > 0);
}

int main(void) {
    printf("=== DW SPI Host Test Harness ===\n");
    hw_model_init(&hw_model);
    hw_model.regs[DW_SPI_VERSION / 4] = DW_HSSI_102A;

    g_dws = &g_dws_struct;
    memset(g_dws, 0, sizeof(*g_dws));
    g_dws->ip = DW_HSSI_ID;
    g_dws->ver = 0;
    g_dws->regs = (void *)(uintptr_t)0;
    g_dws->paddr = 0;
    g_dws->irq = 42;
    g_dws->max_freq = 50000000;
    g_dws->bus_num = 0;
    g_dws->reg_io_width = 4;

    snprintf(g_dev.name, sizeof(g_dev.name), "dw_spi_test");
    int ret = dw_spi_add_controller(&g_dev, g_dws);
    assert(ret == 0);
    g_ctlr = g_dws->ctlr;
    g_ctlr->irq = 42;

    memset(&g_spi, 0, sizeof(g_spi));
    g_spi.controller = g_ctlr;
    g_spi.chip_select = 0;
    g_spi.mode = SPI_MODE_0;
    dw_spi_setup(&g_spi);

    test_register_access();
    test_controller_init();
    test_set_cs();
    test_setup();
    test_poll_transfer_8bit();
    test_irq_transfer();
    test_16bit_transfer();
    test_mem_op_jedec();
    test_mem_op_read();
    test_mem_op_write();
    test_adjust_op_size();
    test_check_status();
    test_suspend_resume();
    test_overflow();

    printf("\n=== Results: %d passed, %d failed ===\n", test_pass, test_fail);
    if (test_fail > 0) return 1;
    return 0;
}
