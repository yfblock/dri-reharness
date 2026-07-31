#include <linux/i2c.h>

void i2c_transaction_access(struct i2c_client *client, unsigned int command,
                            unsigned char *buffer, unsigned int count)
{
    unsigned int value;

    value = i2c_smbus_read_byte(client);
    i2c_smbus_write_byte(client, value);
    value = i2c_smbus_read_byte_data(client, command);
    i2c_smbus_write_byte_data(client, command, value);
    value = i2c_smbus_read_word_data(client, command);
    i2c_smbus_write_word_data(client, command, value);
    value = i2c_smbus_read_word_swapped(client, command);
    i2c_smbus_write_word_swapped(client, command, value);
    value = i2c_smbus_read_block_data(client, command, buffer);
    i2c_smbus_write_block_data(client, command, count, buffer);
    value = i2c_smbus_read_i2c_block_data(client, command, count, buffer);
    i2c_smbus_write_i2c_block_data(client, command, count, buffer);
    value = i2c_master_recv(client, (char *)buffer, count);
    value = i2c_master_send(client, (char *)buffer, count);
}
