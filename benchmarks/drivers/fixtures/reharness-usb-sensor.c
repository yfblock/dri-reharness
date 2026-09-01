// SPDX-License-Identifier: GPL-2.0
/* Deterministic USB control and bulk-OUT fixture for the generic profile. */
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/uaccess.h>
#include <linux/usb.h>

#define REHARNESS_USB_VENDOR 0x0403
#define REHARNESS_USB_PRODUCT 0x6001
#define REHARNESS_USB_GET_MODEM_STATUS 5
#define REHARNESS_USB_ENDPOINT_OUT 2
#define REHARNESS_USB_MAX_PAYLOAD 64

struct reharness_usb_status {
	__u8 value[2];
};

struct reharness_usb_bulk {
	__u8 endpoint;
	__u8 length;
	__u8 data[REHARNESS_USB_MAX_PAYLOAD];
	__u8 actual;
};

#define REHARNESS_USB_GET_STATUS \
	_IOR('U', 0x10, struct reharness_usb_status)
#define REHARNESS_USB_BULK_OUT \
	_IOWR('U', 0x11, struct reharness_usb_bulk)

static struct usb_device *reharness_usb_device;
static DEFINE_MUTEX(reharness_usb_lock);

static int reharness_usb_read_status(struct usb_device *usb,
					     struct reharness_usb_status *status)
{
	return usb_control_msg_recv(usb, 0, REHARNESS_USB_GET_MODEM_STATUS,
					   USB_DIR_IN | USB_TYPE_VENDOR | USB_RECIP_DEVICE,
					   0, 0, status->value, sizeof(status->value),
					   1000, GFP_KERNEL);
}

static long reharness_usb_ioctl(struct file *file, unsigned int command,
					unsigned long argument)
{
	struct reharness_usb_status status;
	struct reharness_usb_bulk request;
	struct usb_device *usb;
	void *bulk_data;
	int actual;
	int ret;

	if (command != REHARNESS_USB_GET_STATUS
			&& command != REHARNESS_USB_BULK_OUT)
		return -ENOTTY;

	mutex_lock(&reharness_usb_lock);
	if (!reharness_usb_device) {
		mutex_unlock(&reharness_usb_lock);
		return -ENODEV;
	}
	usb = usb_get_dev(reharness_usb_device);
	mutex_unlock(&reharness_usb_lock);

	if (command == REHARNESS_USB_GET_STATUS) {
		ret = reharness_usb_read_status(usb, &status);
		usb_put_dev(usb);
		if (ret)
			return ret;
		return copy_to_user((void __user *)argument, &status,
					    sizeof(status)) ? -EFAULT : 0;
	}

	if (copy_from_user(&request, (void __user *)argument, sizeof(request))) {
		usb_put_dev(usb);
		return -EFAULT;
	}
	if (request.endpoint != REHARNESS_USB_ENDPOINT_OUT
			|| request.length == 0
			|| request.length > REHARNESS_USB_MAX_PAYLOAD) {
		usb_put_dev(usb);
		return -ENODEV;
	}

	bulk_data = kmemdup(request.data, request.length, GFP_KERNEL);
	if (!bulk_data) {
		usb_put_dev(usb);
		return -ENOMEM;
	}
	ret = usb_bulk_msg(usb, usb_sndbulkpipe(usb, request.endpoint),
			   bulk_data, request.length, &actual, 1000);
	kfree(bulk_data);
	usb_put_dev(usb);
	if (ret)
		return ret;
	if (actual != request.length)
		return -EIO;
	request.actual = actual;
	return copy_to_user((void __user *)argument, &request,
				    sizeof(request)) ? -EFAULT : 0;
}

static const struct file_operations reharness_usb_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = reharness_usb_ioctl,
};

static struct miscdevice reharness_usb_control_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "reharness-usb-control",
	.fops = &reharness_usb_fops,
	.mode = 0666,
};

static int reharness_usb_probe(struct usb_interface *interface,
				       const struct usb_device_id *id)
{
	struct usb_device *usb = interface_to_usbdev(interface);
	struct reharness_usb_status status;
	int ret;

	ret = reharness_usb_read_status(usb, &status);
	if (ret)
		return ret;

	mutex_lock(&reharness_usb_lock);
	if (reharness_usb_device) {
		mutex_unlock(&reharness_usb_lock);
		return -EBUSY;
	}
	reharness_usb_device = usb_get_dev(usb);
	mutex_unlock(&reharness_usb_lock);

	ret = misc_register(&reharness_usb_control_device);
	if (ret) {
		mutex_lock(&reharness_usb_lock);
		usb_put_dev(reharness_usb_device);
		reharness_usb_device = NULL;
		mutex_unlock(&reharness_usb_lock);
		return ret;
	}
	usb_set_intfdata(interface, &reharness_usb_control_device);
	dev_info(&interface->dev,
		 "REHARNESS_USB_DRIVER_PROBE status=0x%02x 0x%02x\n",
		 status.value[0], status.value[1]);
	return 0;
}

static void reharness_usb_disconnect(struct usb_interface *interface)
{
	struct usb_device *usb;

	usb_set_intfdata(interface, NULL);
	misc_deregister(&reharness_usb_control_device);
	mutex_lock(&reharness_usb_lock);
	usb = reharness_usb_device;
	reharness_usb_device = NULL;
	mutex_unlock(&reharness_usb_lock);
	if (usb)
		usb_put_dev(usb);
	dev_info(&interface->dev, "REHARNESS_USB_DRIVER_DISCONNECT\n");
}

static const struct usb_device_id reharness_usb_ids[] = {
	{ USB_DEVICE(REHARNESS_USB_VENDOR, REHARNESS_USB_PRODUCT) },
	{ }
};
MODULE_DEVICE_TABLE(usb, reharness_usb_ids);

static struct usb_driver reharness_usb_driver = {
	.name = "reharness_usb_sens",
	.probe = reharness_usb_probe,
	.disconnect = reharness_usb_disconnect,
	.id_table = reharness_usb_ids,
};

module_usb_driver(reharness_usb_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic USB control and bulk-OUT fixture");
