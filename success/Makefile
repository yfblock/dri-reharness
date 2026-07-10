obj-m += edu_drv.o
KERNELDIR ?= /home/yfblock/Code/linux
all:
	$(MAKE) -C $(KERNELDIR) M=$(PWD) modules
clean:
	$(MAKE) -C $(KERNELDIR) M=$(PWD) clean
