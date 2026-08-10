#include "dw-apb-ssi_baremetal.h"


/* Module Function Prototypes */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs_high, uint32_t enable, uint32_t cs);
void dw_spi_check_status(struct dw_apb_ssi_priv *dev, uint32_t raw);
void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev);
void dw_spi_irq(struct dw_apb_ssi_priv *dev);
void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0, uint32_t clk_div, uint32_t speed_hz, uint32_t tmode, uint32_t ndf, uint32_t chip_rx_sample_dly);
void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t level);
void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint32_t len, int32_t ret, uint32_t retry);
void dw_spi_add_controller(struct dw_apb_ssi_priv *dev, int32_t ret);
void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev);
void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode);
void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *dev);
void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dev);
void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dev, uint32_t enable);
void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs);

#endif /* DW_APB_SSI_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
int main(void) {
    return 0;
}
#endif