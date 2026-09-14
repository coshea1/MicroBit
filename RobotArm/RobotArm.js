bluetooth.onUartDataReceived(serial.delimiters(Delimiters.Colon), function () {
    msg = bluetooth.uartReadUntil(serial.delimiters(Delimiters.Colon))
    count = 0
    bluetooth.uartWriteString(msg)
})
bluetooth.onBluetoothConnected(function () {
    connected = true
    count = 0
    basic.showString("C")
})
bluetooth.onBluetoothDisconnected(function () {
    basic.showString("D")
    connected = false
    msg = ""
})
let step3 = 0
let step2 = 0
let step1 = 0
let step0 = 0
let connected = false
let count = 0
let msg = ""
let pos0 = 90
let pos1 = 90
let pos2 = 90
let pos3 = 90
Servo.Servo(0, pos0)
Servo.Servo(1, pos1)
Servo.Servo(2, pos2)
Servo.Servo(3, pos3)
bluetooth.startUartService()
basic.showString("R")
basic.forever(function () {
    pos0 = Math.max(0, Math.min(180, pos0 + step0))
    pos1 = Math.max(0, Math.min(180, pos1 + step1))
    pos2 = Math.max(0, Math.min(180, pos2 + step2))
    pos3 = Math.max(0, Math.min(180, pos3 + step3))
    Servo.Servo(0, pos0)
    Servo.Servo(1, pos1)
    Servo.Servo(2, pos2)
    Servo.Servo(3, pos3)
})
basic.forever(function () {
    if (connected == true) {
        if (msg == "a") {
            step0 = 1
            // base rotate left
            basic.showArrow(ArrowNames.West)
            msg = ""
        } else if (msg == "d") {
            step0 = -1
            // base rotate right
            basic.showArrow(ArrowNames.East)
            msg = ""
        } else if (msg == "w") {
            step1 = 1
            // shoulder up
            basic.showArrow(ArrowNames.North)
            msg = ""
        } else if (msg == "s") {
            step1 = -1
            // shoulder down
            basic.showArrow(ArrowNames.South)
            msg = ""
        } else if (msg == "i") {
            step2 = 1
            // elbow up
            basic.showArrow(ArrowNames.SouthWest)
            msg = ""
        } else if (msg == "k") {
            step2 = -1
            // elbow down
            basic.showArrow(ArrowNames.SouthEast)
            msg = ""
        } else if (msg == "j") {
            step3 = 1
            // wrist up
            basic.showArrow(ArrowNames.NorthWest)
            msg = ""
        } else if (msg == "l") {
            step3 = -1
            // wrist down
            basic.showArrow(ArrowNames.NorthEast)
            msg = ""
        } else {
            step0 = 0
            step1 = 0
            step2 = 0
            step3 = 0
        }
    }
})
basic.forever(function () {
    if (connected == true) {
        count += 1
        basic.pause(1000)
        if (count == 120) {
            control.reset()
        }
    }
})
