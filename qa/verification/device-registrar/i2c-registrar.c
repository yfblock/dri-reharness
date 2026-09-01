// SPDX-License-Identifier: GPL-2.0
/* Deterministic I2C adapter and client fixture for QEMU profile tests. */
#include <linux/i2c.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/uaccess.h>

#define REHARNESS_I2C_ADDRESS 0x50
#define REHARNESS_I2C_REGISTER 0x10
#define REHARNESS_I2C_READ _IOWR('R', 0x10, struct reharness_i2c_request)
#define REHARNESS_I2C_WRITE _IOW('R', 0x11, struct reharness_i2c_request)

struct reharness_i2c_request {
	u8 address;
	u8 reg;
	u8 value;
};

static struct i2c_adapter reharness_i2c_adapter;
static struct i2c_client *reharness_i2c_client;
static DEFINE_MUTEX(reharness_i2c_lock);
static u8 reharness_i2c_registers[256];
static u8 reharness_i2c_selected_register;
static char *client_type = "reharness_i2c_sens";
module_param(client_type, charp, 0444);
MODULE_PARM_DESC(client_type, "I2C client type matched by the driver");

static int reharness_i2c_master_xfer(struct i2c_adapter *adapter,
					struct i2c_msg *messages, int count)
{
	int index;

	if (!messages || count <= 0)
		return -EINVAL;

	mutex_lock(&reharness_i2c_lock);
	for (index = 0; index < count; ++index) {
		struct i2c_msg *message = &messages[index];
		u8 offset;
		int byte;

		if (message->addr != REHARNESS_I2C_ADDRESS) {
			mutex_unlock(&reharness_i2c_lock);
			return -ENXIO;
		}

		if (message->flags & I2C_M_RD) {
			for (byte = 0; byte < message->len; ++byte)
				message->buf[byte] = reharness_i2c_registers[
					reharness_i2c_selected_register++];
			continue;
		}

		if (!message->buf || message->len == 0) {
			mutex_unlock(&reharness_i2c_lock);
			return -EINVAL;
		}
		offset = message->buf[0];
		reharness_i2c_selected_register = offset;
		for (byte = 1; byte < message->len; ++byte)
			reharness_i2c_registers[reharness_i2c_selected_register++] =
				message->buf[byte];
	}
	mutex_unlock(&reharness_i2c_lock);
	return count;
}

static u32 reharness_i2c_functionality(struct i2c_adapter *adapter)
{
	return I2C_FUNC_I2C;
}

static const struct i2c_algorithm reharness_i2c_algorithm = {
	.master_xfer = reharness_i2c_master_xfer,
	.functionality = reharness_i2c_functionality,
};

static int reharness_i2c_control_xfer(struct reharness_i2c_request *request,
					      bool read)
{
	struct i2c_msg messages[2];
	u8 buffer[2];
	int count;
	int ret;

	if (read) {
		buffer[0] = request->reg;
		messages[0] = (struct i2c_msg){
			.addr = request->address,
			.len = 1,
			.buf = buffer,
		};
		messages[1] = (struct i2c_msg){
			.addr = request->address,
			.flags = I2C_M_RD,
			.len = 1,
			.buf = &request->value,
		};
		count = 2;
	} else {
		buffer[0] = request->reg;
		buffer[1] = request->value;
		messages[0] = (struct i2c_msg){
			.addr = request->address,
			.len = 2,
			.buf = buffer,
		};
		count = 1;
	}

	ret = i2c_transfer(&reharness_i2c_adapter, messages, count);
	return ret == count ? 0 : (ret < 0 ? ret : -EIO);
}

static long reharness_i2c_control_ioctl(struct file *file,
					unsigned int command, unsigned long argument)
{
	struct reharness_i2c_request request;
	int ret;

	if (command != REHARNESS_I2C_READ && command != REHARNESS_I2C_WRITE)
		return -ENOTTY;
	if (copy_from_user(&request, (void __user *)argument, sizeof(request)))
		return -EFAULT;

	ret = reharness_i2c_control_xfer(&request,
					 command == REHARNESS_I2C_READ);
	if (ret || command != REHARNESS_I2C_READ)
		return ret;
	if (copy_to_user((void __user *)argument, &request, sizeof(request)))
		return -EFAULT;
	return 0;
}

static const struct file_operations reharness_i2c_control_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = reharness_i2c_control_ioctl,
};

static struct miscdevice reharness_i2c_control_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "reharness-i2c-control",
	.fops = &reharness_i2c_control_fops,
	.mode = 0666,
};

static int __init reharness_i2c_registrar_init(void)
{
	struct i2c_board_info board_info = {
		.addr = REHARNESS_I2C_ADDRESS,
	};
	int ret;

	if (!client_type || !*client_type)
		return -EINVAL;
	strscpy(board_info.type, client_type, sizeof(board_info.type));

	reharness_i2c_registers[REHARNESS_I2C_REGISTER] = 0x5a;
	reharness_i2c_adapter.owner = THIS_MODULE;
	reharness_i2c_adapter.algo = &reharness_i2c_algorithm;
	strscpy(reharness_i2c_adapter.name, "reharness-i2c-adapter",
			sizeof(reharness_i2c_adapter.name));
	i2c_set_adapdata(&reharness_i2c_adapter, NULL);

	ret = i2c_add_adapter(&reharness_i2c_adapter);
	if (ret)
		return ret;

	reharness_i2c_client = i2c_new_client_device(&reharness_i2c_adapter,
							&board_info);
	if (IS_ERR(reharness_i2c_client)) {
		ret = PTR_ERR(reharness_i2c_client);
		reharness_i2c_client = NULL;
		i2c_del_adapter(&reharness_i2c_adapter);
		return ret;
	}
	pr_info("REHARNESS_I2C_CLIENT_READY name=%s bus=%s\n",
		reharness_i2c_client->name,
		dev_name(&reharness_i2c_adapter.dev));

	ret = misc_register(&reharness_i2c_control_device);
	if (ret) {
		i2c_unregister_device(reharness_i2c_client);
		reharness_i2c_client = NULL;
		i2c_del_adapter(&reharness_i2c_adapter);
		return ret;
	}

	pr_info("REHARNESS_I2C_REGISTRAR_READY address=0x%02x\n",
		REHARNESS_I2C_ADDRESS);
	return 0;
}

static void __exit reharness_i2c_registrar_exit(void)
{
	misc_deregister(&reharness_i2c_control_device);
	if (reharness_i2c_client)
		i2c_unregister_device(reharness_i2c_client);
	i2c_del_adapter(&reharness_i2c_adapter);
	pr_info("REHARNESS_I2C_REGISTRAR_UNLOADED\n");
}

module_init(reharness_i2c_registrar_init);
module_exit(reharness_i2c_registrar_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic I2C adapter and client fixture");
