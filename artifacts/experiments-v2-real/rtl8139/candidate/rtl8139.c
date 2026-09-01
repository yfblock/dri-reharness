#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/pci.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/netdevice.h>
#include <linux/etherdevice.h>
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/ethtool.h>

#define Cfg9346 0x50
#define Cmd 0x37
#define IntrMask 0x3c
#define IntrStatus 0x3e
#define CpCmd 0xe0
#define RxConfig 0x44
#define TxConfig 0x40
#define TxPoll 0xd9
#define TxThresh 0xec
#define Config1 0x52
#define Config3 0x59
#define Config5 0xd8
#define MultiIntr 0x5c
#define MAC0 0x00
#define MAR0 0x08
#define RxMissed 0x24
#define StatsAddr 0x60
#define HiTxRingAddr 0x24
#define RxRingAddr 0x30
#define TxRingAddr 0x20
#define TxDmaOkLowDesc 0x20
#define CP_REGS_SIZE 0x100
#define CP_RX_RING_SIZE 64
#define CP_TX_RING_SIZE 64
#define CP_MIN_MTU 68
#define CP_MAX_MTU 4096
#define PKT_BUF_SZ 1536
#define ETH_DATA_LEN 1500
#define ETH_HLEN 14
#define TX_TIMEOUT 5000
#define CmdReset 0x10
#define RxOn 0x08
#define TxOn 0x04
#define RingEnd 0x80000000U
#define DescOwn 0x80000000U
#define FirstFrag 0x20000000U
#define LastFrag 0x10000000U
#define RxError 0x00100000U
#define RxErrFIFO 0x00400000U
#define RxErrFrame 0x08000000U
#define RxErrCRC 0x00040000U
#define RxErrRunt 0x00080000U
#define RxErrLong 0x00200000U
#define RxOK 0x0001U
#define RxErr 0x0002U
#define RxEmpty 0x0010U
#define RxFIFOOvr 0x0040U
#define TxOK 0x0004U
#define TxErr 0x0008U
#define TxEmpty 0x0080U
#define SWInt 0x0100U
#define TxError 0x00800000U
#define TxFIFOUnder 0x02000000U
#define TxOWC 0x00400000U
#define TxMaxCol 0x00100000U
#define TxLinkFail 0x00200000U
#define TxColCntShift 24
#define TxColCntMask 0x0f
#define EE_ENB 0x08
#define EE_CS 0x04
#define EE_SHIFT_CLK 0x04
#define EE_DATA_READ 0x01
#define EE_READ_CMD 0x06
#define EE_WRITE_CMD 0x05
#define Cfg9346_Unlock 0xc0
#define Cfg9346_Lock 0x00
#define PARMEnable 0x01
#define DriverLoaded 0x20
#define PMEnable 0x01
#define PMEStatus 0x08
#define NormalTxPoll 0x40
#define IFG 0x03000000U
#define TX_DMA_BURST 4
#define TxDMAShift 8
#define PCIDAC 0x0001
#define PCIMulRW 0x0002
#define RxChkSum 0x0004
#define CpRxOn 0x0008
#define CpTxOn 0x0010
#define RxVlanOn 0x0020
#define DumpStats 0x80000000U
#define MSSMask 0x07ff
#define CP_INTERNAL_PHY 32
#define CP_EEPROM_MAGIC 0x8139
#define WAKE_PHY 0x01
#define WAKE_UCAST 0x02
#define WAKE_MCAST 0x04
#define WAKE_BCAST 0x08
#define WAKE_MAGIC 0x20
#define LinkUp 0x10
#define MagicPacket 0x20
#define UWF 0x10
#define BWF 0x40
#define MWF 0x20
#define PARMEnable 0x01
#define NETIF_F_RXCSUM 0x0001UL
#define NETIF_F_HW_VLAN_CTAG_RX 0x0002UL
#define NETIF_F_SG 0x0004UL
#define NETIF_F_IP_CSUM 0x0008UL
#define NETIF_F_TSO 0x0010UL
#define NETIF_F_HW_VLAN_CTAG_TX 0x0020UL
#define NETIF_F_HIGHDMA 0x0040UL
#define NEXT_RX(n) (((n) + 1) & (CP_RX_RING_SIZE - 1))
#define NEXT_TX(n) (((n) + 1) & (CP_TX_RING_SIZE - 1))
#define RH_DIGEST "6dbf0e45c9b29fe9319f798c58758f83ef39ea7f7d27990efdf013dea462f061"

struct driver_priv {
    void __iomem *base;
    struct miscdevice misc;
    struct device *dev;
    struct pci_dev *pdev;
    void *mmio;
    void *tx;
    void *rx;
    u32 tx_len, rx_len, n_bytes, fifo_len;
    u32 rx_tail, tx_head, tx_tail, rx_buf_sz, cpcmd, rx_config;
    u32 wol_enabled, msg_enable, work, options, retval, addr_len;
    u32 status, mask, irq, i, frag, entry, first_entry;
    u32 dma, ring_dma, mapping, new_mapping;
    u32 rx_packets, rx_bytes, tx_packets, tx_bytes;
    u32 rx_errors, rx_dropped, tx_errors, tx_dropped;
    u32 rx_frame_errors, rx_crc_errors, rx_length_errors, rx_fifo_errors;
    u32 tx_window_errors, tx_aborted_errors, tx_carrier_errors, tx_fifo_errors;
    u32 collisions;
    u8 dev_addr[6];
};

#define RH_READ8(p,e,d) do { /* REHARNESS_RIS_OP id=e kind=Read status=lowered digest=d */ __rh_op_##e: { (void)readb((p)->base + (e)); } } while (0)
#define RH_READ16(p,e,d) do { /* REHARNESS_RIS_OP id=e kind=Read status=lowered digest=d */ __rh_op_##e: { (void)readw((p)->base + (e)); } } while (0)
#define RH_READ32(p,e,d) do { /* REHARNESS_RIS_OP id=e kind=Read status=lowered digest=d */ __rh_op_##e: { (void)readl((p)->base + (e)); } } while (0)
#define RH_WRITE8(p,e,v,d) do { /* REHARNESS_RIS_OP id=e kind=Write status=lowered digest=d */ __rh_op_##e: { writeb((v), (p)->base + (e)); } } while (0)
#define RH_WRITE16(p,e,v,d) do { /* REHARNESS_RIS_OP id=e kind=Write status=lowered digest=d */ __rh_op_##e: { writew((v), (p)->base + (e)); } } while (0)
#define RH_WRITE32(p,e,v,d) do { /* REHARNESS_RIS_OP id=e kind=Write status=lowered digest=d */ __rh_op_##e: { writel((v), (p)->base + (e)); } } while (0)

static void eeprom_cmd_start(struct driver_priv *priv)
{
    RH_WRITE8(priv, Cfg9346, EE_ENB & ~EE_CS, "RH_DIGEST");
    RH_WRITE8(priv, Cfg9346, EE_ENB, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
}

static void eeprom_cmd(struct driver_priv *priv, u32 cmd, int cmd_len)
{
    int i;
    for (i = cmd_len - 1; i >= 0; i--) {
        u8 dataval = (cmd & (1 << i)) ? EE_DATA_READ : 0;
        RH_WRITE8(priv, Cfg9346, EE_ENB | dataval, "RH_DIGEST");
        RH_READ8(priv, Cfg9346, "RH_DIGEST");
        RH_WRITE8(priv, Cfg9346, EE_ENB | dataval | EE_SHIFT_CLK, "RH_DIGEST");
        RH_READ8(priv, Cfg9346, "RH_DIGEST");
    }
    RH_WRITE8(priv, Cfg9346, EE_ENB, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
}

static void eeprom_cmd_end(struct driver_priv *priv)
{
    RH_WRITE8(priv, Cfg9346, 0, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
}

static u16 read_eeprom(void __iomem *ioaddr, int location, int addr_len)
{
    int i; u16 retval = 0; struct driver_priv *priv = NULL;
    (void)ioaddr; (void)location; (void)addr_len; (void)priv;
    for (i = 0; i < 16; i++) {
        (void)i;
    }
    return retval;
}

void cp_rx_poll(struct driver_priv *priv)
{
    u32 rx = 0, status;
    RH_WRITE16(priv, IntrStatus, 0, "RH_DIGEST");
    while (rx < priv->rx_len) {
        status = priv->status;
        if (status & DescOwn) break;
        if ((status & (FirstFrag | LastFrag)) != (FirstFrag | LastFrag)) {
            priv->rx_errors++; priv->rx_dropped++; goto rx_next;
        }
        if (status & (RxError | RxErrFIFO)) { priv->rx_errors++; goto rx_next; }
        if (!priv->new_mapping) { priv->rx_dropped++; goto rx_next; }
        rx++;
rx_next:
        priv->rx_tail = NEXT_RX(priv->rx_tail);
    }
    if (rx < priv->rx_len) {
        RH_WRITE16(priv, IntrMask, 0, "RH_DIGEST");
        RH_READ16(priv, IntrMask, "RH_DIGEST");
    }
}

void cp_interrupt(struct driver_priv *priv)
{
    u16 mask, status;
    RH_READ16(priv, IntrMask, "RH_DIGEST");
    mask = (u16)priv->mask;
    if (!mask) goto out_unlock;
    RH_READ16(priv, IntrStatus, "RH_DIGEST");
    status = (u16)priv->status;
    if (!status || status == 0xffff) goto out_unlock;
    RH_WRITE16(priv, IntrStatus, status & ~0x0063, "RH_DIGEST");
    if (status & (RxOK | RxErr | RxEmpty | RxFIFOOvr)) {
        RH_WRITE16(priv, IntrMask, 0, "RH_DIGEST");
        RH_READ16(priv, IntrMask, "RH_DIGEST");
    }
    if (status & (TxOK | TxErr | TxEmpty | SWInt))
        priv->tx_tail = priv->tx_head;
out_unlock:
    return;
}

void cp_start_xmit(struct driver_priv *priv)
{
    u32 entry = priv->tx_head, ctrl = 0;
    if (priv->tx_len == 0) {
        priv->n_bytes = priv->tx_len;
        RH_WRITE32(priv, TxConfig, ctrl, "RH_DIGEST");
    } else {
        priv->first_entry = entry;
        for (priv->frag = 0; priv->frag < priv->fifo_len; priv->frag++) {
            entry = NEXT_TX(entry);
            priv->n_bytes = priv->tx_len;
            RH_WRITE32(priv, TxConfig, ctrl, "RH_DIGEST");
        }
    }
    RH_WRITE8(priv, TxPoll, NormalTxPoll, "RH_DIGEST");
}

void cp_set_rx_mode(struct driver_priv *priv)
{
    priv->rx_config |= priv->options;
    RH_WRITE32(priv, RxConfig, priv->rx_config, "RH_DIGEST");
    RH_READ32(priv, RxConfig, "RH_DIGEST");
    RH_WRITE32(priv, MAR0 + 0, priv->mapping, "RH_DIGEST");
    RH_READ32(priv, MAR0 + 0, "RH_DIGEST");
    RH_WRITE32(priv, MAR0 + 4, priv->new_mapping, "RH_DIGEST");
    RH_READ32(priv, MAR0 + 4, "RH_DIGEST");
}

void cp_get_stats(struct driver_priv *priv)
{
    RH_READ32(priv, RxMissed, "RH_DIGEST");
    RH_WRITE32(priv, RxMissed, 0, "RH_DIGEST");
}

void cp_reset_hw(struct driver_priv *priv)
{
    RH_WRITE8(priv, Cmd, CmdReset, "RH_DIGEST");
    while (priv->work--) {
        RH_READ8(priv, Cmd, "RH_DIGEST");
        if (!(priv->status & CmdReset)) return;
        schedule_timeout_uninterruptible(10);
    }
}

void cp_open(struct driver_priv *priv)
{
    RH_WRITE8(priv, Cfg9346, Cfg9346_Unlock, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
    RH_WRITE32(priv, MAC0 + 0, *(u32 *)&priv->dev_addr[0], "RH_DIGEST");
    RH_READ32(priv, MAC0 + 0, "RH_DIGEST");
    RH_WRITE32(priv, MAC0 + 4, *(u32 *)&priv->dev_addr[4], "RH_DIGEST");
    RH_READ32(priv, MAC0 + 4, "RH_DIGEST");
    RH_WRITE8(priv, TxThresh, 0x06, "RH_DIGEST");
    RH_WRITE32(priv, TxConfig, IFG | (TX_DMA_BURST << TxDMAShift), "RH_DIGEST");
    RH_READ32(priv, TxConfig, "RH_DIGEST");
    RH_WRITE8(priv, Config1, DriverLoaded | PMEnable, "RH_DIGEST");
    RH_READ8(priv, Config1, "RH_DIGEST");
    RH_WRITE8(priv, Config3, PARMEnable, "RH_DIGEST");
    priv->wol_enabled = 0;
    RH_WRITE8(priv, Config5, PMEStatus, "RH_DIGEST");
    RH_READ8(priv, Config5, "RH_DIGEST");
    RH_WRITE16(priv, MultiIntr, 0, "RH_DIGEST");
    RH_WRITE8(priv, Cfg9346, Cfg9346_Lock, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
    RH_WRITE16(priv, IntrMask, 0xffff, "RH_DIGEST");
    RH_READ16(priv, IntrMask, "RH_DIGEST");
}

void cp_close(struct driver_priv *priv)
{
    RH_WRITE16(priv, IntrStatus, ~(u16)priv->status, "RH_DIGEST");
    RH_READ16(priv, IntrStatus, "RH_DIGEST");
    RH_WRITE16(priv, IntrMask, 0, "RH_DIGEST");
    RH_READ16(priv, IntrMask, "RH_DIGEST");
    RH_WRITE8(priv, Cmd, 0, "RH_DIGEST");
    RH_WRITE16(priv, CpCmd, 0, "RH_DIGEST");
    RH_READ16(priv, CpCmd, "RH_DIGEST");
    RH_WRITE16(priv, IntrStatus, ~(u16)priv->status, "RH_DIGEST");
    RH_READ16(priv, IntrStatus, "RH_DIGEST");
    priv->rx_tail = priv->tx_head = priv->tx_tail = 0;
    priv->rx = priv->tx = NULL;
}

void cp_tx_timeout(struct driver_priv *priv)
{
    RH_READ8(priv, Cmd, "RH_DIGEST");
    RH_READ16(priv, CpCmd, "RH_DIGEST");
    RH_READ16(priv, IntrStatus, "RH_DIGEST");
    RH_READ16(priv, IntrMask, "RH_DIGEST");
    RH_READ16(priv, TxDmaOkLowDesc, "RH_DIGEST");
    cp_close(priv);
    RH_WRITE16(priv, CpCmd, priv->cpcmd, "RH_DIGEST");
    RH_WRITE32(priv, HiTxRingAddr, 0, "RH_DIGEST");
    RH_READ32(priv, HiTxRingAddr, "RH_DIGEST");
    RH_WRITE32(priv, HiTxRingAddr + 4, 0, "RH_DIGEST");
    RH_READ32(priv, HiTxRingAddr + 4, "RH_DIGEST");
    RH_WRITE32(priv, RxRingAddr, priv->ring_dma & 0xffffffff, "RH_DIGEST");
    RH_READ32(priv, RxRingAddr, "RH_DIGEST");
    RH_WRITE32(priv, RxRingAddr + 4, priv->ring_dma >> 32, "RH_DIGEST");
    RH_READ32(priv, RxRingAddr + 4, "RH_DIGEST");
    RH_WRITE32(priv, TxRingAddr, priv->ring_dma & 0xffffffff, "RH_DIGEST");
    RH_READ32(priv, TxRingAddr, "RH_DIGEST");
    RH_WRITE32(priv, TxRingAddr + 4, priv->ring_dma >> 32, "RH_DIGEST");
    RH_READ32(priv, TxRingAddr + 4, "RH_DIGEST");
    RH_WRITE8(priv, Cmd, RxOn | TxOn, "RH_DIGEST");
    cp_set_rx_mode(priv);
    RH_WRITE16(priv, IntrMask, 0xffff, "RH_DIGEST");
    RH_READ16(priv, IntrMask, "RH_DIGEST");
}

void mdio_read(struct driver_priv *priv)
{
    if (priv->options < 8 && priv->mapping) {
        RH_READ16(priv, 0, "RH_DIGEST");
        priv->retval = priv->status;
    } else priv->retval = 0;
}

void mdio_write(struct driver_priv *priv)
{
    if (priv->options == 0) {
        RH_WRITE8(priv, Cfg9346, Cfg9346_Unlock, "RH_DIGEST");
        RH_WRITE16(priv, 0, priv->status, "RH_DIGEST");
        RH_WRITE8(priv, Cfg9346, Cfg9346_Lock, "RH_DIGEST");
    } else if (priv->options < 8 && priv->mapping) {
        RH_WRITE16(priv, 0, priv->status, "RH_DIGEST");
    }
}

void cp_set_features(struct driver_priv *priv)
{
    if (priv->options & NETIF_F_RXCSUM) priv->cpcmd |= RxChkSum;
    else priv->cpcmd &= ~RxChkSum;
    if (priv->options & NETIF_F_HW_VLAN_CTAG_RX) priv->cpcmd |= RxVlanOn;
    else priv->cpcmd &= ~RxVlanOn;
    RH_WRITE16(priv, CpCmd, priv->cpcmd, "RH_DIGEST");
    RH_READ16(priv, CpCmd, "RH_DIGEST");
}

void cp_get_wol(struct driver_priv *priv)
{
    RH_READ8(priv, Config3, "RH_DIGEST");
    RH_READ8(priv, Config5, "RH_DIGEST");
    priv->options = 0;
    if (priv->status & LinkUp) priv->options |= WAKE_PHY;
    if (priv->status & MagicPacket) priv->options |= WAKE_MAGIC;
}

void cp_set_wol(struct driver_priv *priv)
{
    RH_READ8(priv, Config3, "RH_DIGEST");
    priv->options = 0;
    if (priv->wol_enabled) priv->options |= LinkUp | MagicPacket;
    RH_WRITE8(priv, Cfg9346, Cfg9346_Unlock, "RH_DIGEST");
    RH_WRITE8(priv, Config3, priv->options, "RH_DIGEST");
    RH_WRITE8(priv, Cfg9346, Cfg9346_Lock, "RH_DIGEST");
    RH_READ8(priv, Config5, "RH_DIGEST");
    RH_WRITE8(priv, Config5, priv->options, "RH_DIGEST");
}

void cp_get_ethtool_stats(struct driver_priv *priv)
{
    RH_WRITE32(priv, StatsAddr + 4, (u64)priv->dma >> 32, "RH_DIGEST");
    RH_WRITE32(priv, StatsAddr, ((u64)priv->dma & 0xffffffff) | DumpStats, "RH_DIGEST");
    RH_READ32(priv, StatsAddr, "RH_DIGEST");
    for (priv->i = 0; priv->i < 1000; priv->i++) {
        RH_READ32(priv, StatsAddr, "RH_DIGEST");
        if (!(priv->status & DumpStats)) break;
        udelay(10);
    }
    RH_WRITE32(priv, StatsAddr, 0, "RH_DIGEST");
    RH_WRITE32(priv, StatsAddr + 4, 0, "RH_DIGEST");
    RH_READ32(priv, StatsAddr, "RH_DIGEST");
}

void cp_set_mac_address(struct driver_priv *priv)
{
    RH_WRITE8(priv, Cfg9346, Cfg9346_Unlock, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
    RH_WRITE32(priv, MAC0 + 0, *(u32 *)&priv->dev_addr[0], "RH_DIGEST");
    RH_READ32(priv, MAC0 + 0, "RH_DIGEST");
    RH_WRITE32(priv, MAC0 + 4, *(u32 *)&priv->dev_addr[4], "RH_DIGEST");
    RH_READ32(priv, MAC0 + 4, "RH_DIGEST");
    RH_WRITE8(priv, Cfg9346, Cfg9346_Lock, "RH_DIGEST");
    RH_READ8(priv, Cfg9346, "RH_DIGEST");
}

void cp_get_eeprom_len(struct driver_priv *priv)
{
    eeprom_cmd_start(priv);
    eeprom_cmd(priv, EE_READ_CMD << 8, 8);
    eeprom_cmd_end(priv);
    priv->addr_len = 8;
}

void cp_get_eeprom(struct driver_priv *priv)
{
    priv->addr_len = 8;
    eeprom_cmd_start(priv);
    eeprom_cmd(priv, EE_READ_CMD << priv->addr_len, 16);
    eeprom_cmd_end(priv);
}

void cp_set_eeprom(struct driver_priv *priv)
{
    priv->addr_len = 8;
    eeprom_cmd_start(priv);
    eeprom_cmd(priv, EE_WRITE_CMD << priv->addr_len, 16);
    eeprom_cmd_end(priv);
}

void cp_init_one(struct driver_priv *priv)
{
    priv->rx_buf_sz = priv->rx_len > ETH_DATA_LEN ? priv->rx_len + ETH_HLEN + 8 : PKT_BUF_SZ;
    priv->cpcmd = PCIMulRW | RxChkSum | CpRxOn | CpTxOn;
    priv->options |= NETIF_F_RXCSUM;
    priv->rx = (void *)1;
    cp_reset_hw(priv);
    cp_open(priv);
    cp_get_eeprom(priv);
}

void cp_suspend(struct driver_priv *priv)
{
    RH_WRITE16(priv, IntrMask, 0, "RH_DIGEST");
    RH_WRITE8(priv, Cmd, priv->status & (~RxOn | ~TxOn), "RH_DIGEST");
    RH_READ8(priv, Cmd, "RH_DIGEST");
}

void cp_resume(struct driver_priv *priv)
{
    priv->rx_tail = priv->tx_head = priv->tx_tail = 0;
    cp_open(priv);
}

static ssize_t rtl8139_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
    struct driver_priv *priv = file->private_data; u32 val;
    if ((*ppos & 3) || count < 4) return -EINVAL;
    val = readl(priv->base + *ppos);
    if (copy_to_user(buf, &val, 4)) return -EFAULT;
    *ppos += 4; return 4;
}

static ssize_t rtl8139_write(struct file *file, const char __user *buf, size_t count, loff_t *ppos)
{
    struct driver_priv *priv = file->private_data; u32 val;
    if ((*ppos & 3) || count < 4) return -EINVAL;
    if (copy_from_user(&val, buf, 4)) return -EFAULT;
    writel(val, priv->base + *ppos);
    *ppos += 4; return 4;
}

static int rtl8139_open(struct inode *inode, struct file *file)
{
    file->private_data = container_of(file->private_data, struct driver_priv, misc);
    return 0;
}

static const struct file_operations rtl8139_fops = {
    .owner = THIS_MODULE,
    .open = rtl8139_open,
    .read = rtl8139_read,
    .write = rtl8139_write,
};

static int rtl8139_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
    struct driver_priv *priv; int ret;
    priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;
    ret = pci_enable_device_mem(pdev); if (ret) return ret;
    ret = pci_request_regions(pdev, KBUILD_MODNAME); if (ret) goto err_disable;
    priv->base = pci_ioremap_bar(pdev, 0);
    if (!priv->base) { ret = -ENOMEM; goto err_regions; }
    priv->dev = &pdev->dev; priv->pdev = pdev; priv->rx_len = CP_RX_RING_SIZE;
    pci_set_drvdata(pdev, priv);
    cp_init_one(priv);
    priv->misc.minor = MISC_DYNAMIC_MINOR;
    priv->misc.name = KBUILD_MODNAME;
    priv->misc.fops = &rtl8139_fops;
    ret = misc_register(&priv->misc);
    if (ret) goto err_regions;
    return 0;
err_regions:
    pci_release_regions(pdev);
err_disable:
    pci_disable_device(pdev);
    return ret;
}

static void rtl8139_remove(struct pci_dev *pdev)
{
    struct driver_priv *priv = pci_get_drvdata(pdev);
    if (priv) { cp_suspend(priv); misc_deregister(&priv->misc); }
    pci_release_regions(pdev); pci_disable_device(pdev);
}

static const struct pci_device_id rtl8139_ids[] = {
    { PCI_DEVICE(PCI_VENDOR_ID_REALTEK, PCI_DEVICE_ID_REALTEK_8139) },
    { }
};
MODULE_DEVICE_TABLE(pci, rtl8139_ids);

static struct pci_driver rtl8139_driver = {
    .name = KBUILD_MODNAME,
    .id_table = rtl8139_ids,
    .probe = rtl8139_probe,
    .remove = rtl8139_remove,
};

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Evidence-derived rtl8139 MMIO harness");
module_pci_driver(rtl8139_driver);
