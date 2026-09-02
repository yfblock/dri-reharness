/* Minimal standalone edu driver: same register protocol, no kernel headers */
typedef unsigned int u32;
typedef unsigned long long u64;
typedef unsigned int __u32;
#define IO_ID            0x00
#define IO_IRQ_STATUS    0x24
#define IO_IRQ_ACK       0x64
#define IO_DMA_SRC       0x80
#define IO_DMA_DST       0x88
#define IO_DMA_CNT       0x90
#define IO_DMA_CMD       0x98
static volatile u32 *mmio;
static u32 readl_(volatile u32 *a) { return *a; }
static void writel_(u32 v, volatile u32 *a) { *a = v; }
u32 edu_read(unsigned long off) {
    u32 val;
    switch (off) {
    case 0: val = readl_(mmio + IO_ID); break;
    case 36: val = readl_(mmio + IO_IRQ_STATUS); break;
    default: val = 0; break;
    }
    return val;
}
void edu_write(unsigned long off, u32 v) {
    switch (off) {
    case 36: writel_(v, mmio + IO_IRQ_ACK); break;
    case 152: writel_(v, mmio + 0x98); break;
    default: break;
    }
}
