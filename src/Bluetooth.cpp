
#include "Bluetooth.h"

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#define DEVICE_NAME "ESP32 Ploter"

#define SERVICE_UUID "8e400001-b5a3-f393-a8e9-4bd8c1c5b2a4"
#define RX_UUID      "8e400002-b5a3-f393-a8e9-4bd8c1c5b2a4"
#define TX_UUID      "8e400003-b5a3-f393-a8e9-4bd8c1c5b2a4"


// Constructor
Bluetooth::Bluetooth() {
    txCharacteristic = nullptr;
    advertising = nullptr;
}


// SERVER CALLBACKS
class ServerCallbacks : public BLEServerCallbacks {

private:
    Bluetooth *bluetooth;

public:
    ServerCallbacks(Bluetooth *bt) {
        bluetooth = bt;
    }

    void onConnect(BLEServer *server) override {
        Serial.println("BLE CLIENT CONNECTED");
    }

    void onDisconnect(BLEServer *server) override {
        Serial.println("BLE CLIENT DISCONNECTED");

        bluetooth->restartAdvertising();
    }
};


// RECEIVER CALLBACKS
class ReceiverCallbacks : public BLECharacteristicCallbacks {

private:
    Bluetooth *bluetooth;

public:
    ReceiverCallbacks(Bluetooth *bt) {
        bluetooth = bt;
    }

    void onWrite(BLECharacteristic *characteristic) override {

        String data = characteristic->getValue();

        if (data.length() == 0) return;

        bluetooth->handleReceivedData(data);
    }
};


// START BLE
void Bluetooth::begin() {

    Serial.println("Starting BLE...");

    BLEDevice::init(DEVICE_NAME);
    BLEDevice::setMTU(517);

    BLEServer *server = BLEDevice::createServer();

    server->setCallbacks(new ServerCallbacks(this));

    BLEService *service =
        server->createService(SERVICE_UUID);


    // RX CHARACTERISTIC
    BLECharacteristic *rxCharacteristic =
        service->createCharacteristic(
            RX_UUID,
            BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR
        );


    // TX CHARACTERISTIC
    txCharacteristic =
        service->createCharacteristic(
            TX_UUID,
            BLECharacteristic::PROPERTY_NOTIFY
        );

    txCharacteristic->addDescriptor(new BLE2902());


    // REGISTER CALLBACK
    rxCharacteristic->setCallbacks(
        new ReceiverCallbacks(this)
    );


    // START SERVICE
    service->start();

    advertising = BLEDevice::getAdvertising();

    advertising->addServiceUUID(SERVICE_UUID);
    advertising->setScanResponse(true);

    BLEDevice::startAdvertising();

    Serial.println("ESP32 BLE READY");
    Serial.print("Name: ");Serial.println(DEVICE_NAME);
}


// HANDLE RECEIVED DATA
void Bluetooth::handleReceivedData(String data) {

    Serial.print(data);
    Serial.flush();

    txCharacteristic->setValue("ok");
    txCharacteristic->notify();
}


// RESTART ADVERTISING
void Bluetooth::restartAdvertising() {

    advertising->start();

    Serial.println("Advertising restarted");
}
