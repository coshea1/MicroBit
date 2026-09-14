// Wait for "G:" over Bluetooth UART to start the program
bluetooth.onUartDataReceived(serial.delimiters(Delimiters.Colon), function () {
    receivedData = bluetooth.uartReadUntil(serial.delimiters(Delimiters.Colon))
    if (receivedData == "G") {
        started = true
    }
})
// Also allow Button A to start the program
input.onButtonPressed(Button.A, function () {
    started = true
})
let dist = 0
let left = 0
let right = 0
let maqueenIsMoving = false
let receivedData = ""
let started = false
let honking = false
bluetooth.startUartService()
let waitArrows = [
ArrowNames.North,
ArrowNames.NorthEast,
ArrowNames.East,
ArrowNames.SouthEast,
ArrowNames.South,
ArrowNames.SouthWest,
ArrowNames.West,
ArrowNames.NorthWest
]
started = false
basic.forever(function () {
    if (started && maqueenIsMoving) {
        right = maqueen.readPatrol(maqueen.Patrol.PatrolRight)
        left = maqueen.readPatrol(maqueen.Patrol.PatrolLeft)
        if (left == 0 && right == 0) {
            maqueen.motorRun(maqueen.Motors.All, maqueen.Dir.CW, 17)
        }
        if (left == 0 && right == 1) {
            maqueen.motorRun(maqueen.Motors.M2, maqueen.Dir.CW, 35)
            maqueen.motorStop(maqueen.Motors.M1)
        }
        if (left == 1 && right == 0) {
            maqueen.motorRun(maqueen.Motors.M1, maqueen.Dir.CW, 35)
            maqueen.motorStop(maqueen.Motors.M2)
        }
        if (left == 1 && right == 1) {
            maqueen.motorRun(maqueen.Motors.M2, maqueen.Dir.CW, 35)
            maqueen.motorStop(maqueen.Motors.M1)
        }
    } else {
        maqueen.motorStop(maqueen.Motors.All)
    }
})
// Continuously play the horn tone while honking is true
basic.forever(function () {
    if (started && !(maqueenIsMoving)) {
        // G4
        music.playTone(392, music.beat(BeatFraction.Sixteenth))
        // Eb4
        music.playTone(311, music.beat(BeatFraction.Sixteenth))
        basic.pause(Math.randomRange(500, 3000))
    }
})
basic.forever(function () {
    dist = maqueen.Ultrasonic()
    if (dist <= 10) {
        maqueenIsMoving = false
        maqueen.motorStop(maqueen.Motors.All)
    } else if (!(maqueenIsMoving)) {
        maqueenIsMoving = true
    }
})
basic.forever(function () {
    if (!(started)) {
        for (let arrow of waitArrows) {
            if (started) {
                break;
            }
            basic.showArrow(arrow)
            basic.pause(120)
        }
    }
})
basic.forever(function () {
    if (started) {
        if (maqueenIsMoving) {
            maqueen.writeLED(maqueen.LED.LEDRight, maqueen.LEDswitch.turnOn)
            maqueen.writeLED(maqueen.LED.LEDLeft, maqueen.LEDswitch.turnOff)
            basic.showIcon(IconNames.Happy)
        } else {
            maqueen.writeLED(maqueen.LED.LEDLeft, maqueen.LEDswitch.turnOn)
            maqueen.writeLED(maqueen.LED.LEDRight, maqueen.LEDswitch.turnOff)
            basic.showIcon(IconNames.Sad)
        }
    }
})
