
#include <Arduino.h>
#include "Bluetooth.h"

// Create Bluetooth object
Bluetooth bluetooth;

void setup() {

    Serial.begin(115200);

    delay(1000);

    bluetooth.begin();

}

void loop() {

    delay(100);

}
