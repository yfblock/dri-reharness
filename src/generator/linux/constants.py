"""Shared constants for the Linux backend sub-modules."""
from __future__ import annotations

# State fields that should be bound to device private state during
# expression normalization, rather than left as raw source identifiers.
MODELED_STATE_FIELDS = {
    "bypass_orig", "mask_cache", "skip_init", "ngpio",
    "gpio_dir", "gpio_is", "gpio_ibe", "gpio_iev", "gpio_ie",
    "version", "features",
    "ready", "idev", "evbit", "absbit",
    "virtio_evt_available", "virtio_evt_completed",
    "virtio_evt_outstanding", "virtio_evt_queue_depth",
    "virtio_evt_notified", "virtio_sts_available",
    "virtio_sts_completed", "virtio_sts_outstanding",
    "virtio_sts_queue_depth", "virtio_sts_notified",
    "xfer_mode_shadow",
    "enabled", "suspended", "connected", "remote_wakeup_allowed",
    "halted", "wedged", "dir_in", "periodic", "isochronous",
    "num_eps", "num_channels", "op_state", "lx_state",
    "fifo_size", "fifo_load", "desc_count", "next_desc", "compl_desc",
    "total_data", "target_frame", "frame_number", "dma",
    "hpi_regstep",
    "sie_num",
    "flags", "nr_ports", "max_ports",
}
