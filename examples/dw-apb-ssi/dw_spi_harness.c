#include "dw_apb_ssi_harness.h"

#ifndef module_platform_driver
#define module_platform_driver(drv)  ((void)0)
#endif

#ifndef MODULE_DEVICE_TABLE
#define MODULE_DEVICE_TABLE(bus, tbl)  ((void)0)
#endif

#ifndef __init
#define __init
#endif

#ifndef __exit
#define __exit
#endif

#ifndef __maybe_unused
#define __maybe_unused
#endif

#ifndef __force
#define __force
#endif

#ifndef noinline
#define noinline __attribute__((noinline))
#endif

#ifndef ____cacheline_aligned
#define ____cacheline_aligned __attribute__((aligned(64)))
#endif

/* -----------------------------------------------------------------------
 * Register offset definitions (from evidence.registers)
 * ----------------------------------------------------------------------- */
#define DW_SPI_CTRLR0            0x00   /* offset  0, width B4 */
#define DW_SPI_CTRLR1            0x04   /* offset  4, width B4 */
#define DW_SPI_SSIENR            0x08   /* offset  8, width B4 */
#define DW_SPI_SER               0x10   /* offset 16, width B4 */
#define DW_SPI_BAUDR             0x14   /* offset 20, width B4 */
#define DW_SPI_TXFTLR            0x18   /* offset 24, width B4 */
#define DW_SPI_RXFTLR            0x1C   /* offset 28, width B4 */
#define DW_SPI_TXFLR             0x20   /* offset 32, width B4 */
#define DW_SPI_RXFLR             0x24   /* offset 36, width B4 */
#define DW_SPI_SR                0x28   /* offset 40, width B4 */
#define DW_SPI_IMR               0x2C   /* offset 44, width B4 */
#define DW_SPI_ISR               0x30   /* offset 48, width B4 */
#define DW_SPI_RISR              0x34   /* offset 52, width B4 */
#define DW_SPI_ICR               0x48   /* offset 72, width B4 */
#define DW_SPI_VERSION           0x5C   /* offset 92, width B4 */
#define DW_SPI_RX_SAMPLE_DLY     0xF0   /* offset 240, width B4 */
#define DW_SPI_CS_OVERRIDE       0xF4   /* offset 244, width B4 */
#define MSCC_SPI_MST_SW_MODE     0x14   /* offset  20, width B4 */

/* -----------------------------------------------------------------------
 * Common bit definitions used by dw-apb-ssi
 * ----------------------------------------------------------------------- */
#define DW_SPI_CTRLR0_DFS_MASK   GENMASK(2, 0)
#define DW_SPI_CTRLR0_DFS_4BIT   (0x3)
#define DW_SPI_CTRLR0_DFS_8BIT   (0x7)
#define DW_SPI_CTRLR0_DFS_16BIT  (0xF)
#define DW_SPI_CTRLR0_DFS_32BIT  (0x1F)
#define DW_SPI_CTRLR0_FRF_MASK   GENMASK(5, 4)
#define DW_SPI_CTRLR0_FRF_SPI   (0 << 4)
#define DW_SPI_CTRLR0_FRF_SSP   (1 << 4)
#define DW_SPI_CTRLR0_FRF_MW    (2 << 4)
#define DW_SPI_CTRLR0_MODE_MASK GENMASK(7, 6)
#define DW_SPI_CTRLR0_SCPHA     BIT(6)
#define DW_SPI_CTRLR0_SCPOL     BIT(7)
#define DW_SPI_CTRLR0_TMOD_MASK GENMASK(9, 8)
#define DW_SPI_CTRLR0_TMOD_TR   (0 << 8)
#define DW_SPI_CTRLR0_TMOD_TO   (1 << 8)
#define DW_SPI_CTRLR0_TMOD_RO   (2 << 8)
#define DW_SPI_CTRLR0_TMOD_EPROM (3 << 8)
#define DW_SPI_CTRLR0_SLV_OE    BIT(10)
#define DW_SPI_CTRLR0_SRL       BIT(11)
#define DW_SPI_CTRLR0_SSTE      BIT(24)

#define DW_SPI_SR_BUSY          BIT(0)
#define DW_SPI_SR_TFNF          BIT(1)
#define DW_SPI_SR_TFE           BIT(2)
#define DW_SPI_SR_RFNE          BIT(3)
#define DW_SPI_SR_RFF           BIT(4)
#define DW_SPI_SR_TF_ON         BIT(5)
#define DW_SPI_SR_RF_ON         BIT(6)
#define DW_SPI_SR_ERR           BIT(7)

#define DW_SPI_INT_TXEI        BIT(0)
#define DW_SPI_INT_TXOI        BIT(1)
#define DW_SPI_INT_RXUI        BIT(2)
#define DW_SPI_INT_RXOI        BIT(3)
#define DW_SPI_INT_TXFI       BIT(4)
#define DW_SPI_INT_RXFI       BIT(5)
#define DW_SPI_INT_MSTI       BIT(6)

#define DW_SPI_IMR_MASK        0x7F

#define DW_SPI_DMACR         0x4C
#define DW_SPI_DMATDLR       0x50
#define DW_SPI_DMARDLR       0x54
#define DW_SPI_IDR           0x58

/* -----------------------------------------------------------------------
 * Device private struct
 * bind.state maps dev.base -> dev->base, bind.types DeviceState -> struct dw_apb_ssi_priv
 * ----------------------------------------------------------------------- */
struct dw_apb_ssi_priv {
    uintptr_t       base;       /* dev->base — MMIO base address */
    uintptr_t       mmio;       /* secondary MMIO base (for platform variants) */
    uint32_t        irq;
    uint32_t        fifo_len;
    uint32_t        max_freq;
    uint32_t        reg_io_width;
    uint32_t        num_cs;
    uint32_t        tx_max_len;
    uint32_t        rx_max_len;
    uint32_t        current_freq;
    uint32_t        ctrlr0;
    uint32_t        supported;
    void           *controller_data;
    void           *parent_dev;
    void           *pdev;
    void           *ctlr;
    void           *spi;
    void           *transfer;
    void           *msg;
    void           *mem_op;
    void           *rx;
    void           *tx;
    uint32_t       cs_override;
    uint32_t       *off;
};

/* -----------------------------------------------------------------------
 * Primitive stub implementations (from bind.primitives)
 * ----------------------------------------------------------------------- */
static uint64_t trace_count = 0;

__attribute__((unused))
static uint8_t harness_read8(uintptr_t addr)
{
    volatile uint8_t *p = (volatile uint8_t *)addr;
    uint8_t val = *p;
    printf("[trace %lu] R8  0x%08lx = 0x%02x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    return val;
}

__attribute__((unused))
static uint16_t harness_read16(uintptr_t addr)
{
    volatile uint16_t *p = (volatile uint16_t *)addr;
    uint16_t val = *p;
    printf("[trace %lu] R16 0x%08lx = 0x%04x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    return val;
}

static uint32_t harness_read32(uintptr_t addr)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    uint32_t val = *p;
    printf("[trace %lu] R32 0x%08lx = 0x%08x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    return val;
}

__attribute__((unused))
static uint16_t harness_read16be(uintptr_t addr)
{
    volatile uint16_t *p = (volatile uint16_t *)addr;
    uint16_t raw = *p;
    uint16_t val = ((raw >> 8) & 0xFF) | ((raw & 0xFF) << 8);
    printf("[trace %lu] R16BE 0x%08lx = 0x%04x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    return val;
}

__attribute__((unused))
static uint32_t harness_read32be(uintptr_t addr)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    uint32_t raw = *p;
    uint32_t val = ((raw >> 24) & 0xFF) |
                   ((raw >> 8)  & 0xFF00) |
                   ((raw << 8)  & 0xFF0000) |
                   ((raw << 24) & 0xFF000000);
    printf("[trace %lu] R32BE 0x%08lx = 0x%08x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    return val;
}

__attribute__((unused))
static void harness_write8(uint8_t val, uintptr_t addr)
{
    volatile uint8_t *p = (volatile uint8_t *)addr;
    printf("[trace %lu] W8  0x%08lx = 0x%02x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    *p = val;
}

static void harness_write16(uint16_t val, uintptr_t addr)
{
    volatile uint16_t *p = (volatile uint16_t *)addr;
    printf("[trace %lu] W16 0x%08lx = 0x%04x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    *p = val;
}

static void harness_write32(uint32_t val, uintptr_t addr)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    printf("[trace %lu] W32 0x%08lx = 0x%08x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    *p = val;
}

__attribute__((unused))
static void harness_write16be(uint16_t val, uintptr_t addr)
{
    volatile uint16_t *p = (volatile uint16_t *)addr;
    uint16_t raw = ((val >> 8) & 0xFF) | ((val & 0xFF) << 8);
    printf("[trace %lu] W16BE 0x%08lx = 0x%04x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    *p = raw;
}

__attribute__((unused))
static void harness_write32be(uint32_t val, uintptr_t addr)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    uint32_t raw = ((val >> 24) & 0xFF) |
                  ((val >> 8)  & 0xFF00) |
                  ((val << 8)  & 0xFF0000) |
                  ((val << 24) & 0xFF000000);
    printf("[trace %lu] W32BE 0x%08lx = 0x%08x\n",
           (unsigned long)trace_count++, (unsigned long)addr, val);
    *p = raw;
}

__attribute__((unused))
static void harness_write_w1c8(uint8_t val, uintptr_t addr)
{
    volatile uint8_t *p = (volatile uint8_t *)addr;
    uint8_t cur = *p;
    uint8_t newv = cur & ~val;
    printf("[trace %lu] W1C8  0x%08lx: cur=0x%02x w1c=0x%02x -> 0x%02x\n",
           (unsigned long)trace_count++, (unsigned long)addr, cur, val, newv);
    *p = newv;
}

__attribute__((unused))
static void harness_write_w1c16(uint16_t val, uintptr_t addr)
{
    volatile uint16_t *p = (volatile uint16_t *)addr;
    uint16_t cur = *p;
    uint16_t newv = cur & ~val;
    printf("[trace %lu] W1C16 0x%08lx: cur=0x%04x w1c=0x%04x -> 0x%04x\n",
           (unsigned long)trace_count++, (unsigned long)addr, cur, val, newv);
    *p = newv;
}

__attribute__((unused))
static void harness_write_w1c32(uint32_t val, uintptr_t addr)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    uint32_t cur = *p;
    uint32_t newv = cur & ~val;
    printf("[trace %lu] W1C32 0x%08lx: cur=0x%08x w1c=0x%08x -> 0x%08x\n",
           (unsigned long)trace_count++, (unsigned long)addr, cur, val, newv);
    *p = newv;
}

/* -----------------------------------------------------------------------
 * Function prototypes (from evidence.functions)
 * Parameter types mapped per bind.types:
 *   DeviceState -> struct dw_apb_ssi_priv *
 *   UInt        -> uint32_t
 *   Void        -> void
 * ----------------------------------------------------------------------- */

/* spi-dw-core.c */
void    dw_spi_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
uint32_t dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws);
uint32_t dw_spi_irq(uint32_t irq, struct dw_apb_ssi_priv *dev_id);
uint32_t dw_spi_transfer_one(struct dw_apb_ssi_priv *ctlr,
                             struct dw_apb_ssi_priv *spi,
                             struct dw_apb_ssi_priv *transfer);
void    dw_spi_handle_err(struct dw_apb_ssi_priv *ctlr,
                          struct dw_apb_ssi_priv *msg);
uint32_t dw_spi_target_abort(struct dw_apb_ssi_priv *ctlr);
uint32_t dw_spi_exec_mem_op(struct dw_apb_ssi_priv *mem,
                            struct dw_apb_ssi_priv *op);
uint32_t dw_spi_setup(struct dw_apb_ssi_priv *spi);
void    dw_spi_cleanup(struct dw_apb_ssi_priv *spi);

/* spi-dw-mmio.c */
void    dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
uint32_t dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *pdev,
                                  struct dw_apb_ssi_priv *dwsmmio);
void    dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
uint32_t dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_alpine_init(struct dw_apb_ssi_priv *pdev,
                            struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_hssi_init(struct dw_apb_ssi_priv *pdev,
                         struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_intel_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_mountevans_imc_init(struct dw_apb_ssi_priv *pdev,
                                    struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_canaan_k210_init(struct dw_apb_ssi_priv *pdev,
                                struct dw_apb_ssi_priv *dwsmmio);
void    dw_spi_elba_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
uint32_t dw_spi_elba_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio);
uint32_t dw_spi_mmio_probe(struct dw_apb_ssi_priv *pdev);
uint32_t dw_spi_mmio_suspend(struct dw_apb_ssi_priv *dev);
uint32_t dw_spi_mmio_resume(struct dw_apb_ssi_priv *dev);
void    dw_spi_mmio_remove(struct dw_apb_ssi_priv *pdev);

/* ---- Stub definitions for functions declared above but not defined ---- */
uint32_t dw_spi_exec_mem_op(struct dw_apb_ssi_priv *mem,
                            struct dw_apb_ssi_priv *op)
{ (void)mem; (void)op; return 0; }

uint32_t dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *pdev,
                                  struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{ (void)spi; (void)enable; }

uint32_t dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

uint32_t dw_spi_alpine_init(struct dw_apb_ssi_priv *pdev,
                            struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

uint32_t dw_spi_hssi_init(struct dw_apb_ssi_priv *pdev,
                         struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

uint32_t dw_spi_intel_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

uint32_t dw_spi_mountevans_imc_init(struct dw_apb_ssi_priv *pdev,
                                    struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

uint32_t dw_spi_canaan_k210_init(struct dw_apb_ssi_priv *pdev,
                                struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{ (void)spi; (void)enable; }

uint32_t dw_spi_elba_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio)
{ (void)pdev; (void)dwsmmio; return 0; }

/* -----------------------------------------------------------------------
 * Entry point — main()
 * Instantiates the device and calls each evidence.functions entry in order
 * with zero-initialized / plausible default arguments.
 * ----------------------------------------------------------------------- */
static struct dw_apb_ssi_priv g_dev;       /* zero-initialized global device */

int main(void)
{
    struct dw_apb_ssi_priv *dev = &g_dev;

    /* Plausible defaults for userspace target */
    dev->base = (uintptr_t)0xFE000000;   /* MMIO base address */
    dev->mmio = (uintptr_t)0xFE001000;   /* secondary MMIO base */
    dev->irq  = 42;                       /* logical IRQ number */
    dev->fifo_len = 32;
    dev->max_freq = 50000000;
    dev->reg_io_width = 4;
    dev->num_cs = 4;
    dev->supported = 0xFF;
    dev->current_freq = 25000000;
    uint32_t off_val = 0;
    dev->off = &off_val;

    printf("=== dw-apb-ssi harness: start ===\n");

    /* 1. dw_spi_set_cs (spi-dw-core.c:90, spi_controller.set_cs) */
    printf("\n--- dw_spi_set_cs ---\n");
    dw_spi_set_cs(dev, 1);

    /* 2. dw_spi_transfer_handler (spi-dw-core.c:213, irq) */
    printf("\n--- dw_spi_transfer_handler ---\n");
    dw_spi_transfer_handler(dev);

    /* 3. dw_spi_irq (spi-dw-core.c:251, irq_handler.handler) */
    printf("\n--- dw_spi_irq ---\n");
    dw_spi_irq(dev->irq, dev);

    /* 4. dw_spi_transfer_one (spi-dw-core.c:416, transfer_one) */
    printf("\n--- dw_spi_transfer_one ---\n");
    dw_spi_transfer_one(dev, dev, dev);

    /* 5. dw_spi_handle_err (spi-dw-core.c:478, handle_err) */
    printf("\n--- dw_spi_handle_err ---\n");
    dw_spi_handle_err(dev, dev);

    /* 6. dw_spi_target_abort (spi-dw-core.c:484, target_abort) */
    printf("\n--- dw_spi_target_abort ---\n");
    dw_spi_target_abort(dev);

    /* 7. dw_spi_exec_mem_op (spi-dw-core.c:675, exec_op) */
    printf("\n--- dw_spi_exec_mem_op ---\n");
    dw_spi_exec_mem_op(dev, dev);

    /* 8. dw_spi_setup (spi-dw-core.c:789, setup) */
    printf("\n--- dw_spi_setup ---\n");
    dw_spi_setup(dev);

    /* 9. dw_spi_cleanup (spi-dw-core.c:825, cleanup) */
    printf("\n--- dw_spi_cleanup ---\n");
    dw_spi_cleanup(dev);

    /* 10. dw_spi_mscc_set_cs (spi-dw-mmio.c:77, set_cs) */
    printf("\n--- dw_spi_mscc_set_cs ---\n");
    dw_spi_mscc_set_cs(dev, 1);

    /* 11. dw_spi_mscc_ocelot_init (spi-dw-mmio.c:128, init) */
    printf("\n--- dw_spi_mscc_ocelot_init ---\n");
    dw_spi_mscc_ocelot_init(dev, dev);

    /* 12. dw_spi_mscc_jaguar2_init (spi-dw-mmio.c:135, init) */
    printf("\n--- dw_spi_mscc_jaguar2_init ---\n");
    dw_spi_mscc_jaguar2_init(dev, dev);

    /* 13. dw_spi_sparx5_set_cs (spi-dw-mmio.c:148, set_cs) */
    printf("\n--- dw_spi_sparx5_set_cs ---\n");
    dw_spi_sparx5_set_cs(dev, 1);

    /* 14. dw_spi_mscc_sparx5_init (spi-dw-mmio.c:174, init) */
    printf("\n--- dw_spi_mscc_sparx5_init ---\n");
    dw_spi_mscc_sparx5_init(dev, dev);

    /* 15. dw_spi_alpine_init (spi-dw-mmio.c:203, init) */
    printf("\n--- dw_spi_alpine_init ---\n");
    dw_spi_alpine_init(dev, dev);

    /* 16. dw_spi_hssi_init (spi-dw-mmio.c:219, init) */
    printf("\n--- dw_spi_hssi_init ---\n");
    dw_spi_hssi_init(dev, dev);

    /* 17. dw_spi_intel_init (spi-dw-mmio.c:229, init) */
    printf("\n--- dw_spi_intel_init ---\n");
    dw_spi_intel_init(dev, dev);

    /* 18. dw_spi_mountevans_imc_init (spi-dw-mmio.c:240, init) */
    printf("\n--- dw_spi_mountevans_imc_init ---\n");
    dw_spi_mountevans_imc_init(dev, dev);

    /* 19. dw_spi_canaan_k210_init (spi-dw-mmio.c:255, init) */
    printf("\n--- dw_spi_canaan_k210_init ---\n");
    dw_spi_canaan_k210_init(dev, dev);

    /* 20. dw_spi_elba_set_cs (spi-dw-mmio.c:276, set_cs) */
    printf("\n--- dw_spi_elba_set_cs ---\n");
    dw_spi_elba_set_cs(dev, 1);

    /* 21. dw_spi_elba_init (spi-dw-mmio.c:296, init) */
    printf("\n--- dw_spi_elba_init ---\n");
    dw_spi_elba_init(dev, dev);

    /* 22. dw_spi_mmio_probe (spi-dw-mmio.c:313, platform_driver.probe) */
    printf("\n--- dw_spi_mmio_probe ---\n");
    dw_spi_mmio_probe(dev);

    /* 23. dw_spi_mmio_suspend (spi-dw-mmio.c:393, dev_pm_ops.suspend) */
    printf("\n--- dw_spi_mmio_suspend ---\n");
    dw_spi_mmio_suspend(dev);

    /* 24. dw_spi_mmio_resume (spi-dw-mmio.c:410, dev_pm_ops.resume) */
    printf("\n--- dw_spi_mmio_resume ---\n");
    dw_spi_mmio_resume(dev);

    /* 25. dw_spi_mmio_remove (spi-dw-mmio.c:425, platform_driver.remove) */
    printf("\n--- dw_spi_mmio_remove ---\n");
    dw_spi_mmio_remove(dev);

    printf("\n=== dw-apb-ssi harness: done ===\n");
    return 0;
}

/* ---- part 01 of 03 ---- */
/* =========================================================================
 * Part 1 of 4 — Module function bodies
 *   dw_spi_set_cs
 *   dw_spi_transfer_handler
 *   dw_spi_irq
 *   dw_spi_transfer_one
 *   dw_spi_handle_err
 *   dw_spi_target_abort
 * ========================================================================= */

/* -----------------------------------------------------------------------
 * dw_spi_set_cs  (spi-dw-core.c:90, spi_controller.set_cs)
 * ----------------------------------------------------------------------- */
void dw_spi_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{
    uint32_t cs_high = 0; /* stub: cs_high from controller flags */
    /* spi_get_chipselect(spi, 0) stub */
    uint32_t chip_select = 0;

    if (cs_high == enable) {
        /* REHARNESS_RIS_OP @op_1 [Conservative] digest=80f430a0b4992e04 */
        __rh_op_1: {
            uint32_t val = (0x1 << chip_select);
            harness_write32(val, spi->base + DW_SPI_SER);
        }
    }
    if (!(cs_high == enable)) {
        /* REHARNESS_RIS_OP @op_2 [Conservative] digest=baf8513c30b7be5b */
        __rh_op_2: {
            harness_write32(0x0, spi->base + DW_SPI_SER);
        }
    }
}

/* -----------------------------------------------------------------------
 * dw_spi_transfer_handler  (spi-dw-core.c:213, interrupt_handler)
 * ----------------------------------------------------------------------- */
uint32_t dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws)
{
    uint32_t irq_status;
    uint32_t ret = 0;
    uint32_t new_mask = 0;
    uint32_t __return_read_0 = 0;
    uint32_t rxw = 0;
    uint32_t tx_room = 0;
    uint32_t txw = 0;

    /* Read ISR */
    /* REHARNESS_RIS_OP @op_3 [Exact] digest=1da529e7a809836c */
    __rh_op_3: {
        irq_status = harness_read32(dws->base + DW_SPI_ISR);
    }

    /* dw_spi_check_status(dws, false) — stubbed as true */
    if (1) {
        if (0) {
            /* REHARNESS_RIS_OP @op_4 [Conservative] digest=f69675ec9835d413 */
            __rh_op_4: {
                ret = harness_read32(dws->base + DW_SPI_RISR);
            }
        }
        if (1) {
            /* REHARNESS_RIS_OP @op_5 [Conservative] digest=cc3597eae4a4ffcf */
            __rh_op_5: {
                ret = harness_read32(dws->base + DW_SPI_ISR);
            }
        }
        if (ret) {
            /* REHARNESS_RIS_OP @op_6 [Conservative] digest=6b1f7c3c7aff2599 */
            __rh_op_6: {
                harness_write32((0 ? 1 : 0), dws->base + DW_SPI_SSIENR);
            }
            /* REHARNESS_RIS_OP @op_7 [Conservative] digest=3485f4c43857a432 */
            __rh_op_7: {
                __return_read_0 = harness_read32(dws->base + DW_SPI_IMR);
            }
            new_mask = __return_read_0 & ~0x3f;
            /* REHARNESS_RIS_OP @op_8 [Conservative] digest=d8f3ef33fb01544e */
            __rh_op_8: {
                harness_write32(new_mask, dws->base + DW_SPI_IMR);
            }
            /* REHARNESS_RIS_OP @op_9 [Conservative] digest=484f59ac79ec2a84 */
            __rh_op_9: {
                __return_read_0 = harness_read32(dws->base + DW_SPI_ICR);
            }
            /* REHARNESS_RIS_OP @op_10 [Conservative] digest=02bf20c4b2910e68 */
            __rh_op_10: {
                harness_write32(0x0, dws->base + DW_SPI_SER);
            }
            /* REHARNESS_RIS_OP @op_11 [Conservative] digest=dfd1fa2d71073b6b */
            __rh_op_11: {
                harness_write32((1 ? 1 : 0), dws->base + DW_SPI_SSIENR);
            }
            if (dws->ctlr) {
                /* op_12: STATE(dws->ctlr->cur_msg->status) := ret */
                __rh_op_12: {
                    /* stub: cannot deref void*; record state change */
                    (void)ret;
                }
            }
        }
    }

    /* Read RXFLR for reader loop count */
    uint32_t max;
    /* REHARNESS_RIS_OP @op_13 [Exact] digest=143382d23f314b96 */
    __rh_op_13: {
        __return_read_0 = harness_read32(dws->base + DW_SPI_RXFLR);
    }
    max = __return_read_0;

    /* LOOP while max-- (count=max; relation=post-decrement; bounded) */
    while (max--) {
        if (dws->reg_io_width == 0x2) {
            /* REHARNESS_RIS_OP @op_14 [Conservative] digest=8b4a46336bcb6168 */
            __rh_op_14: {
                rxw = harness_read16(dws->base + 0x0);
            }
        }
        if (dws->reg_io_width == 0x4) {
            /* REHARNESS_RIS_OP @op_15 [Conservative] digest=88533cfff9f6ba43 */
            __rh_op_15: {
                rxw = harness_read32(dws->base + 0x0);
            }
        }
        if (dws->rx) {
            uint32_t n_bytes = 1;
            if (n_bytes == 0x1) {
                /* op_16: OUT(*(u8 *)(dws->rx)) := rxw */
                __rh_op_16: {
                    *(uint8_t *)dws->rx = (uint8_t)rxw;
                }
            }
            if (!(n_bytes == 0x1)) {
                if (n_bytes == 0x2) {
                    /* op_17: OUT(*(u16 *)(dws->rx)) := rxw */
                    __rh_op_17: {
                        *(uint16_t *)dws->rx = (uint16_t)rxw;
                    }
                }
                if (!(n_bytes == 0x2)) {
                    /* op_18: OUT(*(u32 *)(dws->rx)) := rxw */
                    __rh_op_18: {
                        *(uint32_t *)dws->rx = (uint32_t)rxw;
                    }
                }
            }
            /* op_19: STATE(dws->rx) := (dws->rx + dws->n_bytes) */
            __rh_op_19: {
                dws->rx = (void *)((uintptr_t)dws->rx + n_bytes);
            }
        }
        /* op_20: STATE(dws->rx_len) := (dws->rx_len + -1) */
        __rh_op_20: {
            /* rx_len not in struct; stub */
        }
    }

    /* Check if rx_len == 0 — stub as true */
    uint32_t rx_len_zero = 1;
    if (rx_len_zero) {
        /* REHARNESS_RIS_OP @op_21 [Conservative] digest=3485f4c43857a432 */
        __rh_op_21: {
            __return_read_0 = harness_read32(dws->base + DW_SPI_IMR);
        }
        new_mask = __return_read_0 & ~0x3f;
        /* REHARNESS_RIS_OP @op_22 [Conservative] digest=d8f3ef33fb01544e */
        __rh_op_22: {
            harness_write32(new_mask, dws->base + DW_SPI_IMR);
        }
    }
    if (!rx_len_zero) {
        /* REHARNESS_RIS_OP @op_23 [Conservative] digest=19789ced0ff377bf */
        __rh_op_23: {
            __return_read_0 = harness_read32(dws->base + DW_SPI_RXFTLR);
        }
        uint32_t rx_len_stub = 1;
        if (rx_len_stub <= __return_read_0) {
            /* REHARNESS_RIS_OP @op_24 [Conservative] digest=048897f03058f8c8 */
            __rh_op_24: {
                harness_write32((rx_len_stub - 0x1), dws->base + DW_SPI_RXFTLR);
            }
        }
    }

    if (irq_status & 0x1) {
        /* REHARNESS_RIS_OP @op_25 [Conservative] digest=d5ec643b5880dd09 */
        __rh_op_25: {
            tx_room = harness_read32(dws->base + DW_SPI_TXFLR);
        }
        (void)tx_room;
        /* op_26: txw := VALUE(0x0) */
        __rh_op_26: {
            txw = 0x0;
        }
        uint32_t max_tx = 16; /* stub: fifo_len - tx_room */
        /* LOOP while max-- (count=max; relation=post-decrement; bounded) */
        while (max_tx--) {
            if (dws->tx) {
                uint32_t n_bytes = 1;
                if (n_bytes == 0x1) {
                    /* op_27: txw := VALUE(*(u8 *)(dws->tx)) */
                    __rh_op_27: {
                        txw = *(uint8_t *)dws->tx;
                    }
                }
                if (!(n_bytes == 0x1)) {
                    if (n_bytes == 0x2) {
                        /* op_28: txw := VALUE(*(u16 *)(dws->tx)) */
                        __rh_op_28: {
                            txw = *(uint16_t *)dws->tx;
                        }
                    }
                    if (!(n_bytes == 0x2)) {
                        /* op_29: txw := VALUE(*(u32 *)(dws->tx)) */
                        __rh_op_29: {
                            txw = *(uint32_t *)dws->tx;
                        }
                    }
                }
                /* op_30: STATE(dws->tx) := (dws->tx + dws->n_bytes) */
                __rh_op_30: {
                    dws->tx = (void *)((uintptr_t)dws->tx + n_bytes);
                }
            }
            if (dws->reg_io_width == 0x2) {
                /* REHARNESS_RIS_OP @op_31 [Unknown] digest=112457f059093b11 */
                __rh_op_31: {
                    harness_write16((uint16_t)txw, dws->base + 0x0);
                }
            }
            if (dws->reg_io_width == 0x4) {
                /* REHARNESS_RIS_OP @op_32 [Unknown] digest=c05dc6f3255038c0 */
                __rh_op_32: {
                    harness_write32(txw, dws->base + 0x0);
                }
            }
            /* op_33: STATE(dws->tx_len) := (dws->tx_len + -1) */
            __rh_op_33: {
                /* stub */
            }
        }
        /* Check tx_len == 0 — stub as true */
        uint32_t tx_len_zero = 1;
        if (tx_len_zero) {
            /* REHARNESS_RIS_OP @op_34 [Conservative] digest=3485f4c43857a432 */
            __rh_op_34: {
                __return_read_0 = harness_read32(dws->base + DW_SPI_IMR);
            }
            new_mask = __return_read_0 & ~0x3f;
            /* REHARNESS_RIS_OP @op_35 [Conservative] digest=d8f3ef33fb01544e */
            __rh_op_35: {
                harness_write32(new_mask, dws->base + DW_SPI_IMR);
            }
        }
    }

    return 0;
}

/* -----------------------------------------------------------------------
 * dw_spi_irq  (spi-dw-core.c:251, irq_handler.handler)
 * ----------------------------------------------------------------------- */
uint32_t dw_spi_irq(uint32_t irq, struct dw_apb_ssi_priv *dev_id)
{
    struct dw_apb_ssi_priv *dws = dev_id;
    uint32_t __return_read_0 = 0;
    uint32_t new_mask = 0;

    /* op_36: ctlr := VALUE(dev_id) */
    __rh_op_36: {
        /* stub: ctlr assignment from dev_id */
        (void)dev_id;
    }

    uint32_t ctlr_isr;
    /* REHARNESS_RIS_OP @op_37 [Exact] digest=e9c17db3dbc213e5 */
    __rh_op_37: {
        ctlr_isr = harness_read32(dws->base + DW_SPI_ISR);
    }

    /* (ctlr->cur_msg == 0x0) — stub as false */
    uint32_t cur_msg_null = 0;
    if (cur_msg_null) {
        /* REHARNESS_RIS_OP @op_38 [Conservative] digest=3485f4c43857a432 */
        __rh_op_38: {
            __return_read_0 = harness_read32(dws->base + DW_SPI_IMR);
        }
        new_mask = __return_read_0 & ~0x3f;
        /* REHARNESS_RIS_OP @op_39 [Conservative] digest=d8f3ef33fb01544e */
        __rh_op_39: {
            harness_write32(new_mask, dws->base + DW_SPI_IMR);
        }
    }

    (void)irq;
    (void)ctlr_isr;
    return 0;
}

/* -----------------------------------------------------------------------
 * dw_spi_transfer_one  (spi-dw-core.c:416, transfer_one)
 * ----------------------------------------------------------------------- */
#include <stdlib.h>
struct dw_spi_chip;
static inline uint32_t spi_get_chipselect(struct dw_apb_ssi_priv *spi, int idx) {
    (void)spi;
    (void)idx;
    return 0;
}
uint32_t dw_spi_transfer_one(struct dw_apb_ssi_priv *ctlr,
                             struct dw_apb_ssi_priv *spi,
                             struct dw_apb_ssi_priv *transfer)
{
    struct dw_apb_ssi_priv *dws = ctlr;
    uint32_t __return_read_0 = 0;
    uint32_t new_mask = 0;
    uint32_t ret = 0;
    uint32_t tx_room = 0;
    uint32_t txw = 0;
    uint32_t rxw = 0;
    void *tx_ptr = NULL;
    void *rx_ptr = NULL;

    struct { uint32_t tmode; uint32_t dfs; uint32_t freq; uint32_t ndf; } cfg;
    __rh_op_40: {
        cfg.tmode = DW_SPI_CTRLR0_TMOD_TR;
        cfg.dfs = 8;
        cfg.freq = 50000000;
        cfg.ndf = 0;
    }

    __rh_op_41: { /* stub: dma_mapped not in struct */ }
    __rh_op_42: { tx_ptr = NULL; /* stub */ }
    __rh_op_43: { /* stub */ }
    __rh_op_44: { rx_ptr = NULL; /* stub */ }
    __rh_op_45: { /* stub */ }

    __rh_op_46: { harness_write32((0 ? 1 : 0), dws->base + DW_SPI_SSIENR); }

    uint32_t cr0;
    __rh_op_47: { cr0 = 0; }
    uint32_t dfs_offset = 0;
    __rh_op_48: { cr0 = (cr0 | ((cfg.dfs - 0x1) << dfs_offset)); }

    uint32_t is_pssi = 1;
    if (is_pssi) {
        __rh_op_49: { cr0 = (cr0 | FIELD_PREP(DW_SPI_CTRLR0_TMOD_MASK, cfg.tmode)); }
    }
    if (!is_pssi) {
        __rh_op_50: {
            uint32_t DW_HSSI_CTRLR0_TMOD_MASK = GENMASK(1, 0);
            cr0 = (cr0 | FIELD_PREP(DW_HSSI_CTRLR0_TMOD_MASK, cfg.tmode));
        }
    }

    __rh_op_51: { harness_write32(cr0, dws->base + DW_SPI_CTRLR0); }

    if ((cfg.tmode == 0x3) || (cfg.tmode == 0x2)) {
        __rh_op_52: { harness_write32((cfg.ndf ? (cfg.ndf - 0x1) : 0x0), dws->base + DW_SPI_CTRLR1); }
    }

    uint32_t speed_hz = 25000000;
    uint32_t clk_div = 2;
    if (dws->current_freq != speed_hz) {
        __rh_op_53: { harness_write32(clk_div, dws->base + DW_SPI_BAUDR); }
        __rh_op_54: { dws->current_freq = speed_hz; }
    }

    uint32_t cur_rx_sample_dly = 0;
    uint32_t chip_rx_sample_dly = 0;
    if (cur_rx_sample_dly != chip_rx_sample_dly) {
        __rh_op_55: { harness_write32(chip_rx_sample_dly, dws->base + DW_SPI_RX_SAMPLE_DLY); }
        __rh_op_56: { /* stub */ }
    }

    __rh_op_57: { /* stub */ }

    __rh_op_58: { __return_read_0 = harness_read32(dws->base + DW_SPI_IMR); }
    new_mask = __return_read_0 | 0x1f;
    __rh_op_59: { harness_write32(new_mask, dws->base + DW_SPI_IMR); }
    __rh_op_60: { harness_write32((1 ? 1 : 0), dws->base + DW_SPI_SSIENR); }

    uint32_t dma_mapped_zero = 1;
    if (dma_mapped_zero) {
        uint32_t irq_poll = 1;
        if (irq_poll) {
            struct { uint32_t unit; uint32_t value; } delay;
            __rh_op_61: { delay.unit = 0x2; }

            uint32_t rx_len_stub = 1, tx_len_stub = 0;
            uint32_t do_iter = 0;
            do {
                __rh_op_62: { tx_room = harness_read32(dws->base + DW_SPI_TXFLR); }
                __rh_op_63: { txw = 0x0; }
                uint32_t max_tx = 16;
                while (max_tx--) {
                    if (tx_ptr) {
                        uint32_t n_bytes = 1;
                        if (n_bytes == 0x1) {
                            __rh_op_64: { txw = *(uint8_t *)tx_ptr; }
                        }
                        if (!(n_bytes == 0x1)) {
                            if (n_bytes == 0x2) {
                                __rh_op_65: { txw = *(uint16_t *)tx_ptr; }
                            }
                            if (!(n_bytes == 0x2)) {
                                __rh_op_66: { txw = *(uint32_t *)tx_ptr; }
                            }
                        }
                        __rh_op_67: { tx_ptr = (void *)((uintptr_t)tx_ptr + n_bytes); }
                    }
                    if (dws->reg_io_width == 0x2) {
                        __rh_op_68: { harness_write16((uint16_t)txw, dws->base + 0x0); }
                    }
                    if (dws->reg_io_width == 0x4) {
                        __rh_op_69: { harness_write32(txw, dws->base + 0x0); }
                    }
                    __rh_op_70: { /* stub */ }
                }

                uint32_t nbits = 8;
                __rh_op_71: { delay.value = (nbits * (rx_len_stub - tx_len_stub)); }

                __rh_op_72: { __return_read_0 = harness_read32(dws->base + DW_SPI_RXFLR); }
                uint32_t max_rx = __return_read_0;
                while (max_rx--) {
                    if (dws->reg_io_width == 0x2) {
                        __rh_op_73: { rxw = harness_read16(dws->base + 0x0); }
                    }
                    if (dws->reg_io_width == 0x4) {
                        __rh_op_74: { rxw = harness_read32(dws->base + 0x0); }
                    }
                    if (rx_ptr) {
                        uint32_t n_bytes = 1;
                        if (n_bytes == 0x1) {
                            __rh_op_75: { *(uint8_t *)rx_ptr = (uint8_t)rxw; }
                        }
                        if (!(n_bytes == 0x1)) {
                            if (n_bytes == 0x2) {
                                __rh_op_76: { *(uint16_t *)rx_ptr = (uint16_t)rxw; }
                            }
                            if (!(n_bytes == 0x2)) {
                                __rh_op_77: { *(uint32_t *)rx_ptr = (uint32_t)rxw; }
                            }
                        }
                        __rh_op_78: { rx_ptr = (void *)((uintptr_t)rx_ptr + n_bytes); }
                    }
                    __rh_op_79: { /* stub */ }
                }

                if (1) {
                    __rh_op_80: { ret = harness_read32(dws->base + DW_SPI_RISR); }
                }
                if (!1) {
                    __rh_op_81: { ret = harness_read32(dws->base + DW_SPI_ISR); }
                }
                if (ret) {
                    __rh_op_82: { harness_write32((0 ? 1 : 0), dws->base + DW_SPI_SSIENR); }
                    __rh_op_83: { __return_read_0 = harness_read32(dws->base + DW_SPI_IMR); }
                    new_mask = __return_read_0 & ~0x3f;
                    __rh_op_84: { harness_write32(new_mask, dws->base + DW_SPI_IMR); }
                    __rh_op_85: { __return_read_0 = harness_read32(dws->base + DW_SPI_ICR); }
                    __rh_op_86: { harness_write32(0x0, dws->base + DW_SPI_SER); }
                    __rh_op_87: { harness_write32((1 ? 1 : 0), dws->base + DW_SPI_SSIENR); }
                    if (dws->ctlr) {
                        __rh_op_88: { (void)ret; }
                    }
                }

                do_iter++;
                if (do_iter >= 1) break;
            } while (rx_len_stub);
            (void)delay;
        }
    }

    uint32_t level = dws->fifo_len / 2;
    __rh_op_89: { harness_write32(level, dws->base + DW_SPI_TXFTLR); }
    __rh_op_90: { harness_write32((level - 0x1), dws->base + DW_SPI_RXFTLR); }

    __rh_op_91: { /* stub */ }

    uint32_t imask;
    __rh_op_92: { imask = ((((0x1 | 0x2) | 0x4) | 0x8) | 0x10); }

    __rh_op_93: { __return_read_0 = harness_read32(dws->base + DW_SPI_IMR); }
    new_mask = (__return_read_0 & ~imask) | (imask & (0x1 | 0x2 | 0x4 | 0x8 | 0x10));
    __rh_op_94: { harness_write32(new_mask, dws->base + DW_SPI_IMR); }

    (void)spi;
    (void)transfer;
    (void)tx_room;
    (void)txw;
    (void)rxw;
    (void)tx_ptr;
    (void)rx_ptr;
    return 0;
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *ctlr,
                       struct dw_apb_ssi_priv *msg)
{
    struct dw_apb_ssi_priv *dws = ctlr;
    uint32_t __return_read_0 = 0;
    uint32_t new_mask = 0;

    __rh_op_95: { harness_write32((0 ? 1 : 0), dws->base + DW_SPI_SSIENR); }
    __rh_op_96: { __return_read_0 = harness_read32(dws->base + DW_SPI_IMR); }
    new_mask = __return_read_0 & ~0x3f;
    __rh_op_97: { harness_write32(new_mask, dws->base + DW_SPI_IMR); }
    __rh_op_98: { __return_read_0 = harness_read32(dws->base + DW_SPI_ICR); }
    __rh_op_99: { harness_write32(0x0, dws->base + DW_SPI_SER); }
    __rh_op_100: { harness_write32((1 ? 1 : 0), dws->base + DW_SPI_SSIENR); }

    (void)msg;
    (void)__return_read_0;
}

uint32_t dw_spi_target_abort(struct dw_apb_ssi_priv *ctlr)
{
    struct dw_apb_ssi_priv *dws = ctlr;
    uint32_t __return_read_0 = 0;
    uint32_t new_mask = 0;

    __rh_op_101: { harness_write32((0 ? 1 : 0), dws->base + DW_SPI_SSIENR); }
    __rh_op_102: { __return_read_0 = harness_read32(dws->base + DW_SPI_IMR); }
    new_mask = __return_read_0 & ~0x3f;
    __rh_op_103: { harness_write32(new_mask, dws->base + DW_SPI_IMR); }
    __rh_op_104: { __return_read_0 = harness_read32(dws->base + DW_SPI_ICR); }
    __rh_op_105: { harness_write32(0x0, dws->base + DW_SPI_SER); }
    __rh_op_106: { harness_write32((1 ? 1 : 0), dws->base + DW_SPI_SSIENR); }

    (void)__return_read_0;
    return 0;
}

/*
 * module dw_spi_setup
 * spi-dw-core.c:789
 */
uint32_t dw_spi_setup(struct dw_apb_ssi_priv *spi)
{
    struct dw_spi_chip *chip = NULL; /* chip == 0x0 */
    uint32_t rx_sample_dly_ns = 0;

    /* IF (chip == 0x0) */
    if (chip == 0x0) {
        /* @op_165: STATE(spi->controller_state) := chip [Conservative] */
        /* REHARNESS_RIS_OP: op_165 Conservative */
        __rh_op_165: { spi->controller_data = chip; }
        (void)&&__rh_op_165;

        /* IF (device_property_read_u32(...) != 0x0) */
        if (1) {
            /* @op_166: rx_sample_dly_ns := VALUE(dws->def_rx_sample_dly_ns) [Conservative] */
            /* REHARNESS_RIS_OP: op_166 Conservative */
            __rh_op_166: { rx_sample_dly_ns = 0; /* dws->def_rx_sample_dly_ns */ }
            (void)&&__rh_op_166;
        }
    }

    (void)rx_sample_dly_ns;
    return 0;
}

/*
 * module dw_spi_cleanup
 * spi-dw-core.c:825
 */
void dw_spi_cleanup(struct dw_apb_ssi_priv *spi)
{
    /* @op_167: STATE(spi->controller_state) := NULL [Exact] */
    /* REHARNESS_RIS_OP: op_167 Exact */
    __rh_op_167: { spi->controller_data = NULL; }
    (void)&&__rh_op_167;
}

/*
 * module dw_spi_mscc_set_cs
 * spi-dw-mmio.c:77
 */
void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{
    struct dw_apb_ssi_priv *dwsmmio = spi;
    struct dw_apb_ssi_priv *dwsmscc = (struct dw_apb_ssi_priv *)dwsmmio->controller_data;
    struct dw_apb_ssi_priv *dws = spi;
    uint32_t cs = spi_get_chipselect(spi, 0);
    uint32_t cs_high = 0;
    uint32_t sw_mode = 0;

    /* @op_168: dwsmscc := VALUE(dwsmmio->priv) [Exact] */
    /* REHARNESS_RIS_OP: op_168 Exact */
    __rh_op_168: { dwsmscc = (struct dw_apb_ssi_priv *)dwsmmio->controller_data; }
    (void)&&__rh_op_168;

    /* IF (cs < 0x4) */
    if (cs < 0x4) {
        /* @op_169: sw_mode := VALUE(0x2000) [Conservative] */
        /* REHARNESS_RIS_OP: op_169 Conservative */
        __rh_op_169: { sw_mode = 0x2000; }
        (void)&&__rh_op_169;

        /* @op_170: W(B4, dwsmscc->spi_mst.MSCC_SPI_MST_SW_MODE) = ((cs < 0x4) ? 0x2000 : sw_mode) -- Config [Conservative] digest=a5b061c01e98438b
         * Address: dwsmscc->mmio + MSCC_SPI_MST_SW_MODE */
        /* REHARNESS_RIS_OP: op_170 Conservative digest=a5b061c01e98438b */
        __rh_op_170: { harness_write32(((cs < 0x4) ? 0x2000 : sw_mode), dwsmscc->mmio + MSCC_SPI_MST_SW_MODE); }
        (void)&&__rh_op_170;
    }

    /* IF (cs_high == enable) */
    if (cs_high == enable) {
        /* @op_171: W(B4, dws->regs.DW_SPI_SER) = (0x1 << spi_get_chipselect(spi, 0)) -- Config [Conservative] digest=80f430a0b4992e04 */
        /* REHARNESS_RIS_OP: op_171 Conservative digest=80f430a0b4992e04 */
        __rh_op_171: { harness_write32((0x1 << spi_get_chipselect(spi, 0)), dws->base + DW_SPI_SER); }
        (void)&&__rh_op_171;
    }

    /* IF ((cs_high == enable) == 0x0) */
    if ((cs_high == enable) == 0x0) {
        /* @op_172: W(B4, dws->regs.DW_SPI_SER) = 0x0 -- Init [Conservative] digest=baf8513c30b7be5b */
        /* REHARNESS_RIS_OP: op_172 Conservative digest=baf8513c30b7be5b */
        __rh_op_172: { harness_write32(0x0, dws->base + DW_SPI_SER); }
        (void)&&__rh_op_172;
    }
}

/*
 * module dw_spi_mscc_ocelot_init
 * spi-dw-mmio.c:128
 */
uint32_t dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio)
{
    struct dw_apb_ssi_priv *dwsmscc = dwsmmio;

    /* @op_173: W(B4, dwsmscc->spi_mst.MSCC_SPI_MST_SW_MODE) = 0x0 -- Init [Exact] digest=f494f1581f787754
     * Address: dwsmscc->mmio + MSCC_SPI_MST_SW_MODE */
    /* REHARNESS_RIS_OP: op_173 Exact digest=f494f1581f787754 */
    __rh_op_173: { harness_write32(0x0, dwsmscc->mmio + MSCC_SPI_MST_SW_MODE); }
    (void)&&__rh_op_173;

    /* @op_174: TXUPDATE[regmap] dwsmscc->syscon@MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL mask=(MSCC_IF_SI_OWNER_MASK << OCELOT_IF_SI_OWNER_OFFSET) value=(MSCC_IF_SI_OWNER_SIMC << OCELOT_IF_SI_OWNER_OFFSET) [Conservative] digest=add72c08c4a3f3a6
     * Modelled as a read-modify-write on dwsmscc->mmio + 0x0 (syscon offset) */
    /* REHARNESS_RIS_OP: op_174 Conservative digest=add72c08c4a3f3a6 */
    __rh_op_174: {
        uint32_t cur = harness_read32(dwsmscc->mmio + 0x0);
        uint32_t mask_val = (0x3U << 4); /* MSCC_IF_SI_OWNER_MASK << OCELOT_IF_SI_OWNER_OFFSET */
        uint32_t value_val = (0x1U << 4); /* MSCC_IF_SI_OWNER_SIMC << OCELOT_IF_SI_OWNER_OFFSET */
        uint32_t new_val = (cur & ~mask_val) | (value_val & mask_val);
        harness_write32(new_val, dwsmscc->mmio + 0x0);
    }
    (void)&&__rh_op_174;

    /* @op_175: STATE(dwsmmio->dws.set_cs) := dw_spi_mscc_set_cs [Exact] */
    /* REHARNESS_RIS_OP: op_175 Exact */
    __rh_op_175: { dwsmmio->transfer = (void *)dw_spi_mscc_set_cs; }
    (void)&&__rh_op_175;

    /* @op_176: STATE(dwsmmio->priv) := dwsmscc [Exact] */
    /* REHARNESS_RIS_OP: op_176 Exact */
    __rh_op_176: { dwsmmio->controller_data = dwsmscc; }
    (void)&&__rh_op_176;

    (void)pdev;
    return 0;
}

/* ---- part 03 of 03 ---- */
/* ===========================================================================
 * dw-apb-ssi — module function bodies (part 3 of 4)
 * Modules: dw_spi_mmio_probe, dw_spi_mmio_suspend, dw_spi_mmio_resume,
 *          dw_spi_mmio_remove
 *
 * This file contains ONLY the bodies of the four evidence.modules functions.
 * The scaffold (includes, struct, primitive stubs, prototypes, main) is in
 * a separate file and must not be repeated here.
 *
 * Address expressions are source-derived: where the RIS uses `dws->regs.<reg>`
 * we emit `pdev->base + <reg_offset>`. Where it uses
 * `dwsmmio->dws.regs.<reg>` we emit `dev->base + <reg_offset>`.
 * =========================================================================== */

/* -----------------------------------------------------------------------
 * Additional constants used by the probe/resume logic
 * ----------------------------------------------------------------------- */
#define DW_PSSI_CTRLR0_DFS_MASK   GENMASK(2, 0)
#define ENOTCONN                  107

/* Helper macros for receipts */
#define REHARNESS_RIS_OP(op_id, kind, digest, addr_expr) \
    printf("REHARNESS_RIS_OP %s %s digest=%s addr=\"%s\"\n", \
           op_id, kind, digest, addr_expr)

/* -----------------------------------------------------------------------
 * dw_spi_mmio_probe
 * ----------------------------------------------------------------------- */
uint32_t dw_spi_mmio_probe(struct dw_apb_ssi_priv *pdev)
{
    uint32_t ret = 0;
    uint32_t init_func = 0;
    uint32_t new_mask = 0;
    uint32_t ser = 0;
    uint32_t cr0 = 0;
    uint32_t tmp = 0;
    uint32_t fifo = 0;
    uint32_t __return_read_0 = 0;

    pdev->irq = 0;

    if (1) {
        pdev->reg_io_width = 0x4;
    }

    if ((init_func && ret) == 0x0) {
        if (1) {
            REHARNESS_RIS_OP("op_209", "W(B4,Config)", "12704bd310147faa",
                             "pdev->base + DW_SPI_SSIENR");
            if (0) goto __rh_op_209;
            __rh_op_209: {
                uint32_t _val = (0x0 ? 0x1 : 0x0);
                harness_write32(_val, pdev->base + DW_SPI_SSIENR);
            }

            REHARNESS_RIS_OP("op_210", "R(B4,Status)", "3485f4c43857a432",
                             "pdev->base + DW_SPI_IMR");
            if (0) goto __rh_op_210;
            __rh_op_210: {
                __return_read_0 = harness_read32(pdev->base + DW_SPI_IMR);
            }

            REHARNESS_RIS_OP("op_211", "W(B4,Config)", "d8f3ef33fb01544e",
                             "pdev->base + DW_SPI_IMR");
            if (0) goto __rh_op_211;
            __rh_op_211: {
                harness_write32(new_mask, pdev->base + DW_SPI_IMR);
            }

            REHARNESS_RIS_OP("op_212", "R(B4,Status)", "484f59ac79ec2a84",
                             "pdev->base + DW_SPI_ICR");
            if (0) goto __rh_op_212;
            __rh_op_212: {
                __return_read_0 = harness_read32(pdev->base + DW_SPI_ICR);
            }

            REHARNESS_RIS_OP("op_213", "W(B4,Init)", "baf8513c30b7be5b",
                             "pdev->base + DW_SPI_SER");
            if (0) goto __rh_op_213;
            __rh_op_213: {
                harness_write32(0x0, pdev->base + DW_SPI_SER);
            }

            REHARNESS_RIS_OP("op_214", "W(B4,Config)", "097f1422079496d8",
                             "pdev->base + DW_SPI_SSIENR");
            if (0) goto __rh_op_214;
            __rh_op_214: {
                uint32_t _val = (0x1 ? 0x1 : 0x0);
                harness_write32(_val, pdev->base + DW_SPI_SSIENR);
            }

            if (pdev->current_freq == 0x0) {
                REHARNESS_RIS_OP("op_215", "R(B4,Status)", "aa8089a02ed821f5",
                                 "pdev->base + DW_SPI_VERSION");
                if (0) goto __rh_op_215;
                __rh_op_215: {
                    pdev->current_freq = harness_read32(pdev->base + DW_SPI_VERSION);
                }
            }

            if (0) {
                pdev->num_cs = 0x1;
            }

            if ((0) == 0x0) {
                if (pdev->num_cs == 0x0) {
                    REHARNESS_RIS_OP("op_217", "W(B4,Config)", "b368885b036e6575",
                                     "pdev->base + DW_SPI_SER");
                    if (0) goto __rh_op_217;
                    __rh_op_217: {
                        harness_write32(0xffff, pdev->base + DW_SPI_SER);
                    }

                    REHARNESS_RIS_OP("op_218", "R(B4,Status)", "f76c38b63a88f273",
                                     "pdev->base + DW_SPI_SER");
                    if (0) goto __rh_op_218;
                    __rh_op_218: {
                        ser = harness_read32(pdev->base + DW_SPI_SER);
                    }

                    REHARNESS_RIS_OP("op_219", "W(B4,Init)", "baf8513c30b7be5b",
                                     "pdev->base + DW_SPI_SER");
                    if (0) goto __rh_op_219;
                    __rh_op_219: {
                        harness_write32(0x0, pdev->base + DW_SPI_SER);
                    }
                }
            }

            if (pdev->fifo_len == 0x0) {
                for (fifo = 1; fifo < 0x100; fifo++) {
                    REHARNESS_RIS_OP("op_220", "W(B4,DataTransfer)",
                                     "ef406851100a35a1",
                                     "pdev->base + DW_SPI_TXFTLR");
                    if (0) goto __rh_op_220;
                    __rh_op_220: {
                        harness_write32(fifo, pdev->base + DW_SPI_TXFTLR);
                    }

                    REHARNESS_RIS_OP("op_221", "R(B4,DataTransfer)",
                                     "987f833a800a50a9",
                                     "pdev->base + DW_SPI_TXFTLR");
                    if (0) goto __rh_op_221;
                    __rh_op_221: {
                        __return_read_0 = harness_read32(pdev->base + DW_SPI_TXFTLR);
                    }
                }

                REHARNESS_RIS_OP("op_222", "W(B4,Init)", "68e4b723c09c7848",
                                 "pdev->base + DW_SPI_TXFTLR");
                if (0) goto __rh_op_222;
                __rh_op_222: {
                    harness_write32(0x0, pdev->base + DW_SPI_TXFTLR);
                }

                pdev->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
            }

            if (1) {
                REHARNESS_RIS_OP("op_224", "R(B4,Config)", "f3a444e105c23d0e",
                                 "pdev->base + DW_SPI_CTRLR0");
                if (0) goto __rh_op_224;
                __rh_op_224: {
                    __return_read_0 = harness_read32(pdev->base + DW_SPI_CTRLR0);
                }

                REHARNESS_RIS_OP("op_225", "W(B4,Config)", "12704bd310147faa",
                                 "pdev->base + DW_SPI_SSIENR");
                if (0) goto __rh_op_225;
                __rh_op_225: {
                    uint32_t _val = (0x0 ? 0x1 : 0x0);
                    harness_write32(_val, pdev->base + DW_SPI_SSIENR);
                }

                REHARNESS_RIS_OP("op_226", "W(B4,Config)", "f3623a102db9f152",
                                 "pdev->base + DW_SPI_CTRLR0");
                if (0) goto __rh_op_226;
                __rh_op_226: {
                    harness_write32(0xffffffff, pdev->base + DW_SPI_CTRLR0);
                }

                REHARNESS_RIS_OP("op_227", "R(B4,Config)", "2a385f9a13ccc6e8",
                                 "pdev->base + DW_SPI_CTRLR0");
                if (0) goto __rh_op_227;
                __rh_op_227: {
                    cr0 = harness_read32(pdev->base + DW_SPI_CTRLR0);
                }

                REHARNESS_RIS_OP("op_228", "W(B4,Config)", "36585b877e2ddf37",
                                 "pdev->base + DW_SPI_CTRLR0");
                if (0) goto __rh_op_228;
                __rh_op_228: {
                    harness_write32(tmp, pdev->base + DW_SPI_CTRLR0);
                }

                REHARNESS_RIS_OP("op_229", "W(B4,Config)", "097f1422079496d8",
                                 "pdev->base + DW_SPI_SSIENR");
                if (0) goto __rh_op_229;
                __rh_op_229: {
                    uint32_t _val = (0x1 ? 0x1 : 0x0);
                    harness_write32(_val, pdev->base + DW_SPI_SSIENR);
                }

                if ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) {
                    pdev->supported |= 0x2;
                }
            }

            if ((1) == 0x0) {
                pdev->supported |= 0x2;
            }

            if (pdev->supported & 0x1) {
                REHARNESS_RIS_OP("op_232", "W(B4,Config)", "0c21730317a5ae2d",
                                 "pdev->base + DW_SPI_CS_OVERRIDE");
                if (0) goto __rh_op_232;
                __rh_op_232: {
                    harness_write32(0xf, pdev->base + DW_SPI_CS_OVERRIDE);
                }
            }
        }

        if (((ret < 0x0) && (ret != (uint32_t)(-ENOTCONN))) == 0x0) {
            if (1) {
                if (1) {
                    if (pdev->max_freq == 0x0) {
                        pdev->max_freq = pdev->max_freq;
                    }
                }
            }
        }

        if (0) {
            if (((pdev->supported & 0x1) == 0x0) ? 1 : 0) {
                if (((ret < 0x0) && (ret != (uint32_t)(-ENOTCONN))) == 0x0) {
                    if (1) {
                        REHARNESS_RIS_OP("op_258", "W(B4,Config)",
                                         "12704bd310147faa",
                                         "pdev->base + DW_SPI_SSIENR");
                        if (0) goto __rh_op_258;
                        __rh_op_258: {
                            uint32_t _val = (0x0 ? 0x1 : 0x0);
                            harness_write32(_val, pdev->base + DW_SPI_SSIENR);
                        }
                    }
                }
            }
        }
    }

    (void)ser; (void)__return_read_0;
    return 0;
}

/* -----------------------------------------------------------------------
 * dw_spi_mmio_suspend
 * ----------------------------------------------------------------------- */
uint32_t dw_spi_mmio_suspend(struct dw_apb_ssi_priv *dev)
{
    REHARNESS_RIS_OP("op_259", "W(B4,Config)", "1d27a789973c926d",
                     "dev->base + DW_SPI_SSIENR");
    if (0) goto __rh_op_259;
    __rh_op_259: {
        uint32_t _val = (0x0 ? 0x1 : 0x0);
        harness_write32(_val, dev->base + DW_SPI_SSIENR);
    }

    REHARNESS_RIS_OP("op_260", "W(B4,Power)", "daa9d26d9fd723fa",
                     "dev->base + DW_SPI_BAUDR");
    if (0) goto __rh_op_260;
    __rh_op_260: {
        harness_write32(0x0, dev->base + DW_SPI_BAUDR);
    }

    return 0;
}

/* -----------------------------------------------------------------------
 * dw_spi_mmio_resume
 * ----------------------------------------------------------------------- */
uint32_t dw_spi_mmio_resume(struct dw_apb_ssi_priv *dev)
{
    uint32_t new_mask = 0;
    uint32_t ser = 0;
    uint32_t cr0 = 0;
    uint32_t tmp = 0;
    uint32_t fifo = 0;
    uint32_t __return_read_0 = 0;

    REHARNESS_RIS_OP("op_261", "W(B4,Config)", "1d27a789973c926d",
                     "dev->base + DW_SPI_SSIENR");
    if (0) goto __rh_op_261;
    __rh_op_261: {
        uint32_t _val = (0x0 ? 0x1 : 0x0);
        harness_write32(_val, dev->base + DW_SPI_SSIENR);
    }

    REHARNESS_RIS_OP("op_262", "R(B4,Status)", "2757833ac7c49d6e",
                     "dev->base + DW_SPI_IMR");
    if (0) goto __rh_op_262;
    __rh_op_262: {
        __return_read_0 = harness_read32(dev->base + DW_SPI_IMR);
    }

    REHARNESS_RIS_OP("op_263", "W(B4,Config)", "8e770f91d3bf2125",
                     "dev->base + DW_SPI_IMR");
    if (0) goto __rh_op_263;
    __rh_op_263: {
        harness_write32(new_mask, dev->base + DW_SPI_IMR);
    }

    REHARNESS_RIS_OP("op_264", "R(B4,Status)", "4c5110b15dd96366",
                     "dev->base + DW_SPI_ICR");
    if (0) goto __rh_op_264;
    __rh_op_264: {
        __return_read_0 = harness_read32(dev->base + DW_SPI_ICR);
    }

    REHARNESS_RIS_OP("op_265", "W(B4,Init)", "0fd5609f15e4b074",
                     "dev->base + DW_SPI_SER");
    if (0) goto __rh_op_265;
    __rh_op_265: {
        harness_write32(0x0, dev->base + DW_SPI_SER);
    }

    REHARNESS_RIS_OP("op_266", "W(B4,Config)", "4645554fd623d2f9",
                     "dev->base + DW_SPI_SSIENR");
    if (0) goto __rh_op_266;
    __rh_op_266: {
        uint32_t _val = (0x1 ? 0x1 : 0x0);
        harness_write32(_val, dev->base + DW_SPI_SSIENR);
    }

    if (dev->current_freq == 0x0) {
        REHARNESS_RIS_OP("op_267", "R(B4,Status)", "49e526b8e39e5d1e",
                         "dev->base + DW_SPI_VERSION");
        if (0) goto __rh_op_267;
        __rh_op_267: {
            dev->current_freq = harness_read32(dev->base + DW_SPI_VERSION);
        }
    }

    if (0) {
        dev->num_cs = 0x1;
    }

    if ((0) == 0x0) {
        if (dev->num_cs == 0x0) {
            REHARNESS_RIS_OP("op_269", "W(B4,Config)", "6a51a80674242213",
                             "dev->base + DW_SPI_SER");
            if (0) goto __rh_op_269;
            __rh_op_269: {
                harness_write32(0xffff, dev->base + DW_SPI_SER);
            }

            REHARNESS_RIS_OP("op_270", "R(B4,Status)", "a239c0939dd0a923",
                             "dev->base + DW_SPI_SER");
            if (0) goto __rh_op_270;
            __rh_op_270: {
                ser = harness_read32(dev->base + DW_SPI_SER);
            }

            REHARNESS_RIS_OP("op_271", "W(B4,Init)", "db1ac64c51360b0f",
                             "dev->base + DW_SPI_SER");
            if (0) goto __rh_op_271;
            __rh_op_271: {
                harness_write32(0x0, dev->base + DW_SPI_SER);
            }
        }
    }

    if (dev->fifo_len == 0x0) {
        for (fifo = 1; fifo < 0x100; fifo++) {
            REHARNESS_RIS_OP("op_272", "W(B4,DataTransfer)",
                             "6037756f276501ed",
                             "dev->base + DW_SPI_TXFTLR");
            if (0) goto __rh_op_272;
            __rh_op_272: {
                harness_write32(fifo, dev->base + DW_SPI_TXFTLR);
            }

            REHARNESS_RIS_OP("op_273", "R(B4,DataTransfer)",
                             "a8a7738fe0a45411",
                             "dev->base + DW_SPI_TXFTLR");
            if (0) goto __rh_op_273;
            __rh_op_273: {
                __return_read_0 = harness_read32(dev->base + DW_SPI_TXFTLR);
            }
        }

        REHARNESS_RIS_OP("op_274", "W(B4,Init)", "3cd05c0ba585bb18",
                         "dev->base + DW_SPI_TXFTLR");
        if (0) goto __rh_op_274;
        __rh_op_274: {
            harness_write32(0x0, dev->base + DW_SPI_TXFTLR);
        }

        dev->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
    }

    if (1) {
        REHARNESS_RIS_OP("op_276", "R(B4,Config)", "71b0f6a0db7be122",
                         "dev->base + DW_SPI_CTRLR0");
        if (0) goto __rh_op_276;
        __rh_op_276: {
            __return_read_0 = harness_read32(dev->base + DW_SPI_CTRLR0);
        }

        REHARNESS_RIS_OP("op_277", "W(B4,Config)", "ee759e5532a5c896",
                         "dev->base + DW_SPI_SSIENR");
        if (0) goto __rh_op_277;
        __rh_op_277: {
            uint32_t _val = (0x0 ? 0x1 : 0x0);
            harness_write32(_val, dev->base + DW_SPI_SSIENR);
        }

        REHARNESS_RIS_OP("op_278", "W(B4,Config)", "84550cb99b28c1bc",
                         "dev->base + DW_SPI_CTRLR0");
        if (0) goto __rh_op_278;
        __rh_op_278: {
            harness_write32(0xffffffff, dev->base + DW_SPI_CTRLR0);
        }

        REHARNESS_RIS_OP("op_279", "R(B4,Config)", "e90c69b23aba4a3e",
                         "dev->base + DW_SPI_CTRLR0");
        if (0) goto __rh_op_279;
        __rh_op_279: {
            cr0 = harness_read32(dev->base + DW_SPI_CTRLR0);
        }

        REHARNESS_RIS_OP("op_280", "W(B4,Config)", "18b2cc7c88f3fcf8",
                         "dev->base + DW_SPI_CTRLR0");
        if (0) goto __rh_op_280;
        __rh_op_280: {
            harness_write32(tmp, dev->base + DW_SPI_CTRLR0);
        }

        REHARNESS_RIS_OP("op_281", "W(B4,Config)", "6b94649b35e76f3b",
                         "dev->base + DW_SPI_SSIENR");
        if (0) goto __rh_op_281;
        __rh_op_281: {
            uint32_t _val = (0x1 ? 0x1 : 0x0);
            harness_write32(_val, dev->base + DW_SPI_SSIENR);
        }

        if ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) {
            dev->supported |= 0x2;
        }
    }

    if ((1) == 0x0) {
        dev->supported |= 0x2;
    }

    if (dev->supported & 0x1) {
        REHARNESS_RIS_OP("op_284", "W(B4,Config)", "5fc38aeec53b0756",
                         "dev->base + DW_SPI_CS_OVERRIDE");
        if (0) goto __rh_op_284;
        __rh_op_284: {
            harness_write32(0xf, dev->base + DW_SPI_CS_OVERRIDE);
        }
    }

    (void)ser; (void)__return_read_0; (void)new_mask;
    return 0;
}

/* -----------------------------------------------------------------------
 * dw_spi_mmio_remove
 * ----------------------------------------------------------------------- */
void dw_spi_mmio_remove(struct dw_apb_ssi_priv *pdev)
{
    REHARNESS_RIS_OP("op_285", "W(B4,Config)", "1d27a789973c926d",
                     "pdev->base + DW_SPI_SSIENR");
    if (0) goto __rh_op_285;
    __rh_op_285: {
        uint32_t _val = (0x0 ? 0x1 : 0x0);
        harness_write32(_val, pdev->base + DW_SPI_SSIENR);
    }

    REHARNESS_RIS_OP("op_286", "W(B4,Power)", "daa9d26d9fd723fa",
                     "pdev->base + DW_SPI_BAUDR");
    if (0) goto __rh_op_286;
    __rh_op_286: {
        harness_write32(0x0, pdev->base + DW_SPI_BAUDR);
    }
}
