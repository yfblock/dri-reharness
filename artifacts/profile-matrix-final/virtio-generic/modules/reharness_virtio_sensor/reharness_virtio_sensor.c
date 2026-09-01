// SPDX-License-Identifier: GPL-2.0-or-later
/* Minimal Virtio block client used by the generic Virtio profile. */
#include <linux/completion.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/virtio.h>
#include <linux/virtio_blk.h>
#include <linux/virtio_config.h>

#define REHARNESS_VIRTIO_READ \
	_IOWR('R', 0x30, struct reharness_virtio_request)

struct reharness_virtio_request {
	__u32 sector;
	__u8 value;
	__u8 status;
};

struct reharness_virtio_io {
	struct virtio_blk_outhdr header;
	__u8 data[512];
	__u8 status;
	struct completion complete;
};

struct reharness_virtio_state {
	struct virtio_device *vdev;
	struct virtqueue *vq;
	struct miscdevice misc;
	struct mutex lock;
	u64 capacity;
};

static void reharness_virtio_done(struct virtqueue *vq)
{
	struct reharness_virtio_io *io;
	unsigned int length;

	while ((io = virtqueue_get_buf(vq, &length)) != NULL)
		complete(&io->complete);
}

static int reharness_virtio_read(struct reharness_virtio_state *state,
					struct reharness_virtio_request *request)
{
	struct reharness_virtio_io *io;
	struct scatterlist sg[3];
	struct scatterlist *sgs[3] = { &sg[0], &sg[1], &sg[2] };
	int ret;

	if ((u64)request->sector >= state->capacity)
		return -EINVAL;

	io = kzalloc(sizeof(*io), GFP_KERNEL);
	if (!io)
		return -ENOMEM;
	init_completion(&io->complete);
	io->status = VIRTIO_BLK_S_IOERR;
	io->header.type = cpu_to_virtio32(state->vdev, VIRTIO_BLK_T_IN);
	io->header.ioprio = cpu_to_virtio32(state->vdev, 0);
	io->header.sector = cpu_to_virtio64(state->vdev, request->sector);
	sg_init_one(&sg[0], &io->header, sizeof(io->header));
	sg_init_one(&sg[1], io->data, sizeof(io->data));
	sg_init_one(&sg[2], &io->status, sizeof(io->status));

	ret = virtqueue_add_sgs(state->vq, sgs, 1, 2, io, GFP_KERNEL);
	if (ret)
		goto out_free;
	if (!virtqueue_kick(state->vq)) {
		ret = -EIO;
		if (virtqueue_detach_unused_buf(state->vq) != io)
			io = NULL;
		goto out_free;
	}
	if (!wait_for_completion_timeout(&io->complete, 5 * HZ)) {
		if (virtqueue_detach_unused_buf(state->vq) == io)
			goto out_free;
		/* Keep an in-flight buffer alive until the transport consumes it. */
		return -ETIMEDOUT;
	}
	if (io->status != VIRTIO_BLK_S_OK) {
		ret = -EIO;
		goto out_free;
	}
	request->value = io->data[0];
	request->status = io->status;
	ret = 0;

out_free:
	kfree(io);
	return ret;
}

static long reharness_virtio_ioctl(struct file *file, unsigned int command,
					   unsigned long argument)
{
	struct reharness_virtio_state *state =
		container_of(file->private_data, struct reharness_virtio_state, misc);
	struct reharness_virtio_request request;
	int ret;

	if (command != REHARNESS_VIRTIO_READ)
		return -ENOTTY;
	if (copy_from_user(&request, (void __user *)argument, sizeof(request)))
		return -EFAULT;

	mutex_lock(&state->lock);
	ret = reharness_virtio_read(state, &request);
	mutex_unlock(&state->lock);
	if (ret)
		return ret;
	if (copy_to_user((void __user *)argument, &request, sizeof(request)))
		return -EFAULT;
	return 0;
}

static const struct file_operations reharness_virtio_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = reharness_virtio_ioctl,
};

static int reharness_virtio_probe(struct virtio_device *vdev)
{
	struct reharness_virtio_state *state;
	int ret;

	state = devm_kzalloc(&vdev->dev, sizeof(*state), GFP_KERNEL);
	if (!state)
		return -ENOMEM;
	state->vdev = vdev;
	mutex_init(&state->lock);
	virtio_cread(vdev, struct virtio_blk_config, capacity, &state->capacity);
	state->vq = virtio_find_single_vq(vdev, reharness_virtio_done,
						 "reharness-read");
	if (IS_ERR(state->vq))
		return PTR_ERR(state->vq);

	state->misc.minor = MISC_DYNAMIC_MINOR;
	state->misc.name = "reharness-virtio-control";
	state->misc.fops = &reharness_virtio_fops;
	state->misc.parent = &vdev->dev;
	vdev->priv = state;
	virtio_device_ready(vdev);
	ret = misc_register(&state->misc);
	if (ret) {
		virtio_reset_device(vdev);
		vdev->config->del_vqs(vdev);
		vdev->priv = NULL;
		return ret;
	}
	dev_info(&vdev->dev,
		 "REHARNESS_VIRTIO_DRIVER_PROBE capacity=%llu\n",
		 (unsigned long long)state->capacity);
	return 0;
}

static void reharness_virtio_remove(struct virtio_device *vdev)
{
	struct reharness_virtio_state *state = vdev->priv;

	misc_deregister(&state->misc);
	virtio_reset_device(vdev);
	vdev->config->del_vqs(vdev);
	vdev->priv = NULL;
}

static const struct virtio_device_id reharness_virtio_ids[] = {
	{ VIRTIO_ID_BLOCK, VIRTIO_DEV_ANY_ID },
	{ 0 },
};

MODULE_DEVICE_TABLE(virtio, reharness_virtio_ids);

static struct virtio_driver reharness_virtio_driver = {
	.driver.name = "reharness_virtio_sensor",
	.id_table = reharness_virtio_ids,
	.probe = reharness_virtio_probe,
	.remove = reharness_virtio_remove,
};

module_virtio_driver(reharness_virtio_driver);

MODULE_DESCRIPTION("Generic Virtio profile verification client");
MODULE_LICENSE("GPL");
