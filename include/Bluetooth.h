
#ifndef BLUETOOTH_H
#define BLUETOOTH_H

#include <Arduino.h>

class BLECharacteristic;
class BLEAdvertising;

class Bluetooth {

public:
    Bluetooth();

    void begin();
    
    void handleReceivedData(String data);
    void restartAdvertising();

private:
    BLECharacteristic *txCharacteristic;
    BLEAdvertising *advertising;

};

#endif