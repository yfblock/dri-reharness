// SPDX-License-Identifier: GPL-2.0
/* Deterministic SPI controller and device fixture for QEMU profile tests. */
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/spi/spi.h>
#include <linux/uaccess.h>

#define REHARNESS_SPI_CHIP_SELECT 0
#define REHARNESS_SPI_REGISTER 0x10
#define REHARNESS_SPI_READ _IOWR('R', 0x20, struct reharness_spi_request)
#define REHARNESS_SPI_WRITE _IOW('R', 0x21, struct reharness_spi_request)

struct reharness_spi_request {
	u8 chip_select;
	u8 reg;
	u8 value;
};

static struct spi_controller *reharness_spi_controller;
static struct spi_device *reharness_spi_device;
static struct spi_device *reharness_spidev_device;
static DEFINE_MUTEX(reharness_spi_lock);
static u8 reharness_spi_registers[256];
static u8 reharness_spi_selected_register;
static char *modalias = "reharness_spi_sens";
module_param(modalias, charp, 0444);
MODULE_PARM_DESC(modalias, "SPI modalias matched by the driver");

static int reharness_spi_setup(struct spi_device *spi)
{
	return spi_get_chipselect(spi, 0) > 1 ? -ENODEV : 0;
}

static int reharness_spi_transfer_one(struct spi_controller *controller,
					      struct spi_device *spi,
					      struct spi_transfer *transfer)
{
	const u8 *tx = transfer->tx_buf;
	u8 *rx = transfer->rx_buf;
	unsigned int byte;

	if (spi_get_chipselect(spi, 0) > 1)
		return -ENODEV;

	mutex_lock(&reharness_spi_lock);
	if (tx && transfer->len) {
		reharness_spi_selected_register = tx[0];
		for (byte = 1; byte < transfer->len; ++byte)
			reharness_spi_registers[reharness_spi_selected_register++] =
				tx[byte];
	}
	if (rx) {
		for (byte = 0; byte < transfer->len; ++byte)
			rx[byte] = reharness_spi_registers[
				reharness_spi_selected_register++];
	}
	mutex_unlock(&reharness_spi_lock);
	return 0;
}

static int reharness_spi_control_xfer(struct reharness_spi_request *request,
					      bool read)
{
	struct spi_message message;
	struct spi_transfer transfers[2] = {};
	u8 tx[2] = { request->reg, request->value };
	int ret;

	if (request->chip_select != REHARNESS_SPI_CHIP_SELECT)
		return -ENODEV;

	spi_message_init(&message);
	if (read) {
		transfers[0].tx_buf = tx;
		transfers[0].len = 1;
		transfers[1].rx_buf = &request->value;
		transfers[1].len = 1;
		spi_message_add_tail(&transfers[0], &message);
		spi_message_add_tail(&transfers[1], &message);
	} else {
		transfers[0].tx_buf = tx;
		transfers[0].len = 2;
		spi_message_add_tail(&transfers[0], &message);
	}

	ret = spi_sync(reharness_spi_device, &message);
	return ret;
}

static long reharness_spi_control_ioctl(struct file *file,
					unsigned int command, unsigned long argument)
{
	struct reharness_spi_request request;
	int ret;

	if (command != REHARNESS_SPI_READ && command != REHARNESS_SPI_WRITE)
		return -ENOTTY;
	if (copy_from_user(&request, (void __user *)argument, sizeof(request)))
		return -EFAULT;

	ret = reharness_spi_control_xfer(&request,
					 command == REHARNESS_SPI_READ);
	if (ret || command != REHARNESS_SPI_READ)
		return ret;
	if (copy_to_user((void __user *)argument, &request, sizeof(request)))
		return -EFAULT;
	return 0;
}

static const struct file_operations reharness_spi_control_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = reharness_spi_control_ioctl,
};

static struct miscdevice reharness_spi_control_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "reharness-spi-control",
	.fops = &reharness_spi_control_fops,
	.mode = 0666,
};

static int __init reharness_spi_registrar_init(void)
{
	struct spi_board_info board_info = {
		.chip_select = REHARNESS_SPI_CHIP_SELECT,
		.max_speed_hz = 1000000,
		.mode = SPI_MODE_0,
	};
	struct spi_board_info spidev_board_info = {
		.modalias = "dh2228fv",
		.chip_select = 1,
		.max_speed_hz = 1000000,
		.mode = SPI_MODE_0,
	};
	int ret;

	if (!modalias || !*modalias)
		return -EINVAL;
	strscpy(board_info.modalias, modalias, sizeof(board_info.modalias));

	reharness_spi_registers[REHARNESS_SPI_REGISTER] = 0xa6;
	ret = misc_register(&reharness_spi_control_device);
	if (ret)
		return ret;

	reharness_spi_controller = spi_alloc_host(
		reharness_spi_control_device.this_device, 0);
	if (!reharness_spi_controller) {
		ret = -ENOMEM;
		goto unregister_misc;
	}
	/* CS0 belongs to the translated client; CS1 is a fixture-owned
	 * userspace endpoint for the in-tree spidev_test tool. */
	reharness_spi_controller->num_chipselect = 2;
	reharness_spi_controller->mode_bits = SPI_MODE_0;
	reharness_spi_controller->bits_per_word_mask = SPI_BPW_MASK(8);
	reharness_spi_controller->max_speed_hz = 1000000;
	reharness_spi_controller->setup = reharness_spi_setup;
	reharness_spi_controller->transfer_one = reharness_spi_transfer_one;

	ret = spi_register_controller(reharness_spi_controller);
	if (ret) {
		spi_controller_put(reharness_spi_controller);
		reharness_spi_controller = NULL;
		goto unregister_misc;
	}

	reharness_spi_device = spi_new_device(reharness_spi_controller,
						      &board_info);
	if (!reharness_spi_device) {
		ret = -ENODEV;
		goto unregister_controller;
	}
	reharness_spidev_device = spi_new_device(reharness_spi_controller,
							 &spidev_board_info);
	if (!reharness_spidev_device) {
		ret = -ENODEV;
		goto unregister_target_device;
	}

	pr_info("REHARNESS_SPI_REGISTRAR_READY chip_select=%d\n",
		REHARNESS_SPI_CHIP_SELECT);
	return 0;

unregister_target_device:
	spi_unregister_device(reharness_spi_device);
	reharness_spi_device = NULL;

unregister_controller:
	spi_unregister_controller(reharness_spi_controller);
	reharness_spi_controller = NULL;
unregister_misc:
	misc_deregister(&reharness_spi_control_device);
	return ret;
}

static void __exit reharness_spi_registrar_exit(void)
{
	if (reharness_spidev_device) {
		spi_unregister_device(reharness_spidev_device);
		reharness_spidev_device = NULL;
	}
	if (reharness_spi_device) {
		spi_unregister_device(reharness_spi_device);
		reharness_spi_device = NULL;
	}
	if (reharness_spi_controller) {
		spi_unregister_controller(reharness_spi_controller);
		reharness_spi_controller = NULL;
	}
	misc_deregister(&reharness_spi_control_device);
	pr_info("REHARNESS_SPI_REGISTRAR_UNLOADED\n");
}

module_init(reharness_spi_registrar_init);
module_exit(reharness_spi_registrar_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic SPI controller and device fixture");
