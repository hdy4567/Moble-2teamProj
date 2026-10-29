#include <Servo.h>
#include <DHT.h>

const int SERVO_PINS[5] = {2, 3, 4, 5, 6};
const int INITIAL_ANGLES[5] = {90, 90, 180, 180, 0};

const int PUL_PIN = 7;
const int DIR_PIN = 8;

// [ALERT] 기존 회로표: RGB R=9, G=10, B=11 / 패시브 부저=12
const int RGB_RED_PIN = 9;
const int RGB_GREEN_PIN = 10;
const int RGB_BLUE_PIN = 11;
const int BUZZER_PIN = 12;
const bool RGB_COMMON_ANODE = false; // 공통 GND=false, 공통 +=true
const unsigned int BUZZER_FREQUENCY_HZ = 2000;
const unsigned long BEEP_ON_MS = 180;
const unsigned long BEEP_OFF_MS = 120;


// [ESTOP] 실물 버튼: D24-GND, INPUT_PULLUP, 눌림=LOW
const int ESTOP_PIN = 24;

// DHT11 (DATA=D22). Adafruit DHT sensor library + Adafruit Unified Sensor required.
const int DHT_PIN = 22;
const int DHT_TYPE = DHT11;
const unsigned long SENSOR_INTERVAL_MS = 3000;
DHT dht(DHT_PIN, DHT_TYPE);
unsigned long lastSensorRead = 0;

// ============================================================
// [FAN] D23: Arduino Mega D23 has NO hardware PWM.
// Drive the fan through an EXTERNAL MOSFET / fan driver with common GND.
// Non-blocking software PWM, preserving conveyor and ultrasonic tasks.
// DHT11 D22 / FAN control D23 (do NOT connect fan directly to D23).
// ============================================================
const byte FAN_PIN = 13;
const unsigned long FAN_PWM_PERIOD_US = 10000UL; // 100 Hz software PWM
int fanSpeed = 50;                               // initial duty (%), 0/50/100
float baseTemp = NAN;
float currentTemp = NAN;
float currentHum = NAN;
float tempDiff = NAN;
const char* temperatureStatus = "NORMAL";
unsigned long fanPwmCycleAt = 0;
bool fanOutputHigh = false;

void setFan(int speed)
{
    fanSpeed = constrain(speed, 0, 100);
}

void updateFanOutput()
{
    // micros() and unsigned subtraction work over timer wraparound.
    unsigned long now = micros();
    if (now - fanPwmCycleAt >= FAN_PWM_PERIOD_US)
    {
        fanPwmCycleAt = now - ((now - fanPwmCycleAt) % FAN_PWM_PERIOD_US);
    }
    unsigned long phase = now - fanPwmCycleAt;
    bool shouldBeHigh = (fanSpeed >= 100) ||
        (fanSpeed > 0 && phase < (FAN_PWM_PERIOD_US * (unsigned long)fanSpeed / 100UL));
    if (shouldBeHigh != fanOutputHigh)
    {
        fanOutputHigh = shouldBeHigh;
        digitalWrite(FAN_PIN, fanOutputHigh ? HIGH : LOW);
    }
}

void updateFanControl(float temperature, float humidity)
{
    // First VALID DHT11 reading becomes the startup temperature reference.
    // Never block conveyor operation waiting for the DHT11.
    currentTemp = temperature;
    currentHum = humidity;
    if (isnan(temperature) || isnan(humidity))
    {
        setFan(100); // fail-safe behavior from the supplied standalone program
        temperatureStatus = "SENSOR_ERROR";
        Serial.println("FAN,100,SENSOR_ERROR");
        return;
    }

    if (isnan(baseTemp))
    {
        baseTemp = temperature;
        Serial.print("DBG,FAN,BASE_TEMP_C=");
        Serial.println(baseTemp, 1);
    }
    tempDiff = temperature - baseTemp;
    if (tempDiff < 0.0f)
        setFan(0);
    else if (tempDiff >= 1.0f)
        setFan(100);
    else
        setFan(50);

    if (fabs(tempDiff) >= 4.0f) temperatureStatus = "EMERGENCY";
    else if (fabs(tempDiff) >= 2.0f) temperatureStatus = "WARNING";
    else temperatureStatus = "NORMAL";

    // New FAN line does not change the existing Raspberry Pi SENSOR protocol.
    // FAN,<percent>,<status>,<diff_C>,<base_temp_C>
    Serial.print("FAN,");
    Serial.print(fanSpeed);
    Serial.print(',');
    Serial.print(temperatureStatus);
    Serial.print(',');
    Serial.print(tempDiff, 1);
    Serial.print(',');
    Serial.println(baseTemp, 1);
}


// [ARRIVAL] Four HC-SR04 modules and four LEDs. Pins 26..46 do not
// overlap conveyor D7/D8, servos D2..D6, DHT D22, or stop D24.
const byte BIN_COUNT = 4;
const byte BIN_TRIG[BIN_COUNT] = {26, 32, 38, 44};
const byte BIN_ECHO[BIN_COUNT] = {27, 33, 39, 45};
const byte BIN_LED[BIN_COUNT] = {28, 34, 40, 46};
const char *BIN_NAMES[BIN_COUNT] = {"ERROR", "SEOUL", "GYEONGGI", "CHUNGCHEONG"};
// ============================================================
// [초음파 감지 거리 설정] 각 수거함별 감지 거리를 개별 변경 (단위: cm)
// 아래 4개의 숫자만 수정하면 됩니다. (예: 10.0f -> 15.0f)
// 배열 순서: 오류 -> 서울 -> 경기 -> 충청 (BIN_NAMES와 동일)
// ============================================================
const float BIN_DETECT_CM[BIN_COUNT] = {
    8.9f, // [0] 오류 수거함 (ERROR)       : TRIG D26 / ECHO D27
    8.45f, // [1] 서울 수거함 (SEOUL)       : TRIG D32 / ECHO D33
    8.7f, // [2] 경기도 수거함 (GYEONGGI)  : TRIG D38 / ECHO D39
    8.69f  // [3] 충청 수거함 (CHUNGCHEONG) : TRIG D44 / ECHO D45
};
const unsigned long BIN_LED_MS = 1000UL;
const unsigned long BIN_INTERVAL_US = 30000UL;
const unsigned long BIN_ECHO_TIMEOUT_US = 25000UL;
const unsigned long BIN_REARM_MS = 300UL;

enum BinObjectState { BIN_WAIT_OBJECT, BIN_COOLDOWN };
BinObjectState binStates[BIN_COUNT] = {
    BIN_WAIT_OBJECT, BIN_WAIT_OBJECT, BIN_WAIT_OBJECT, BIN_WAIT_OBJECT
};
unsigned long binLedSince[BIN_COUNT] = {0, 0, 0, 0};
bool binLedOn[BIN_COUNT] = {false, false, false, false};
unsigned long binEventSeq = 0;

// [DEBUG] All diagnostic messages use DBG, prefix; Raspberry Pi ignores them.
const unsigned long DEBUG_INTERVAL_MS = 2000UL;
unsigned long lastDebugAt = 0;
unsigned long stepTransitions = 0;
unsigned long lastStepTransitions = 0;

void debugBinEvent(const char* event, byte index)
{
    Serial.print("DBG,BIN,");
    Serial.print(BIN_NAMES[index]);
    Serial.print(',');
    Serial.println(event);
}


// Non-blocking HC-SR04 measurement: never use pulseIn() in the stepper loop.
enum EchoPhase { ECHO_IDLE, ECHO_LOW, ECHO_TRIGGER, ECHO_RISE, ECHO_FALL };
EchoPhase echoPhase = ECHO_IDLE;
byte echoSensor = 0;
unsigned long echoPhaseAt = 0;
unsigned long echoCycleAt = 0;
unsigned long echoRiseAt = 0;

void processBinDistance(byte i, float cm)
{
    if (binStates[i] == BIN_COOLDOWN) return;
    if (binStates[i] == BIN_WAIT_OBJECT)
    {
        if (cm > 0.0f && cm <= BIN_DETECT_CM[i])
        {
            // A detected object lights its LED and reports arrival immediately.
            digitalWrite(BIN_LED[i], HIGH);
            binLedSince[i] = millis();
            binLedOn[i] = true;
            binStates[i] = BIN_COOLDOWN;
            debugBinEvent("DETECTED_LED_ON", i);
            Serial.print("BIN,");
            Serial.print(BIN_NAMES[i]);
            Serial.print(',');
            Serial.println(++binEventSeq);
            debugBinEvent("ARRIVAL_SENT_IMMEDIATELY", i);
        }
    }
}

void updateBins()
{
    const unsigned long nowMs = millis();
    for (byte i = 0; i < BIN_COUNT; ++i)
    {
        // Re-arm 300ms after detection, independent of LED duration.
        if (binStates[i] == BIN_COOLDOWN &&
            nowMs - binLedSince[i] >= BIN_REARM_MS)
        {
            binStates[i] = BIN_WAIT_OBJECT;
            debugBinEvent("READY_AGAIN_AFTER_300MS", i);
        }
        // LED stays lit for 1 second after the most recent detection.
        if (binLedOn[i] && nowMs - binLedSince[i] >= BIN_LED_MS)
        {
            digitalWrite(BIN_LED[i], LOW);
            binLedOn[i] = false;
            debugBinEvent("LED_OFF_AFTER_1S", i);
        }
    }

    const unsigned long nowUs = micros();
    switch (echoPhase)
    {
    case ECHO_IDLE:
        if (nowUs - echoCycleAt >= BIN_INTERVAL_US)
        {
            digitalWrite(BIN_TRIG[echoSensor], LOW);
            echoPhaseAt = nowUs;
            echoPhase = ECHO_LOW;
        }
        break;
    case ECHO_LOW:
        if (nowUs - echoPhaseAt >= 2UL)
        {
            digitalWrite(BIN_TRIG[echoSensor], HIGH);
            echoPhaseAt = nowUs;
            echoPhase = ECHO_TRIGGER;
        }
        break;
    case ECHO_TRIGGER:
        if (nowUs - echoPhaseAt >= 10UL)
        {
            digitalWrite(BIN_TRIG[echoSensor], LOW);
            echoPhaseAt = nowUs;
            echoPhase = ECHO_RISE;
        }
        break;
    case ECHO_RISE:
        if (digitalRead(BIN_ECHO[echoSensor]) == HIGH)
        {
            echoRiseAt = nowUs;
            echoPhase = ECHO_FALL;
        }
        else if (nowUs - echoPhaseAt >= BIN_ECHO_TIMEOUT_US)
        {
            processBinDistance(echoSensor, -1.0f);
            echoPhase = ECHO_IDLE;
            echoCycleAt = nowUs;
            echoSensor = (echoSensor + 1) % BIN_COUNT;
        }
        break;
    case ECHO_FALL:
        if (digitalRead(BIN_ECHO[echoSensor]) == LOW)
        {
            processBinDistance(echoSensor, (nowUs - echoRiseAt) / 58.0f);
            echoPhase = ECHO_IDLE;
            echoCycleAt = nowUs;
            echoSensor = (echoSensor + 1) % BIN_COUNT;
        }
        else if (nowUs - echoRiseAt >= BIN_ECHO_TIMEOUT_US)
        {
            processBinDistance(echoSensor, -1.0f);
            echoPhase = ECHO_IDLE;
            echoCycleAt = nowUs;
            echoSensor = (echoSensor + 1) % BIN_COUNT;
        }
        break;
    }
}

const unsigned long RELEASE_DEBOUNCE_MS = 30;

const int CONVEYOR_DIRECTION = LOW; // 반대 방향은 LOW
const unsigned long PULSE_DELAY_US = 140;
const unsigned long RETURN_DELAY_MS = 2000; // 복귀까지 2초

struct MotorCommand
{
    int motorIndex; // 0~4가 실제 모터 1~5
    int angle;
    bool autoReturn;
};

// 시리얼 번호에 따른 동작
const MotorCommand COMMANDS[10] = {
    {4,   0, false}, // 0: 5번 모터 → 0도 유지
    {0, 180, true }, // 1: GREEN 초록색 → 180도 → 90도
    {0,   0, true }, // 2: YELLOW 노란색 → 0도 → 90도
    {1, 180, true }, // 3: 2번 모터 → 180도 → 90도
    {1,   0, true }, // 4: 2번 모터 → 0도 → 90도
    {2, 150, false}, // 5: 3번 모터 → 150도 유지
    {2, 180, false}, // 6: 3번 모터 → 180도 유지
    {3, 150, false}, // 7: 4번 모터 → 150도 유지
    {3, 180, false}, // 8: 4번 모터 → 180도 유지
    {4,  30, false}  // 9: 5번 모터 → 30도 유지
};

Servo motors[5];

bool returnPending[5] = {false};
unsigned long returnStartedAt[5] = {0};

unsigned long lastPulse = 0;
bool pulseState = HIGH;

// [ESTOP] 정지 후에는 새로운 실행 명령을 받아야 재가동합니다.
bool conveyorRunning = true; // 기존 전원 ON 자동 실행 유지
bool physicalPressed = false;
bool releasePending = false;
unsigned long releaseStartedAt = 0;
unsigned long stopRevision = 0;
char startBuffer[16];
int startLength = 0;
bool readingStart = false;
bool discardStart = false;
unsigned long startReceivedAt = 0;

// [ALERT] delay() 없이 LED와 3회 경고음을 처리합니다.
int lastLedRunning = -1;
bool alarmActive = false;
bool alarmToneOn = false;
int alarmBeepsRemaining = 0;
unsigned long alarmChangedAt = 0;

void updateStatusLed()
{
    int running = conveyorRunning ? 1 : 0;
    if (lastLedRunning == running) return;
    lastLedRunning = running;
    int on = RGB_COMMON_ANODE ? LOW : HIGH;
    int off = RGB_COMMON_ANODE ? HIGH : LOW;
    digitalWrite(RGB_RED_PIN, running ? off : on);
    digitalWrite(RGB_GREEN_PIN, running ? on : off);
    digitalWrite(RGB_BLUE_PIN, off);
}

void startInspectionAlarm()
{
    if (alarmActive) return; // 울리는 중 중복 명령은 반복을 늘리지 않음
    alarmActive = true;
    alarmToneOn = true;
    alarmBeepsRemaining = 3;
    alarmChangedAt = millis();
    tone(BUZZER_PIN, BUZZER_FREQUENCY_HZ);
}

void updateInspectionAlarm()
{
    if (!alarmActive) return;
    unsigned long now = millis();
    unsigned long interval = alarmToneOn ? BEEP_ON_MS : BEEP_OFF_MS;
    if (now - alarmChangedAt < interval) return;
    alarmChangedAt = now;
    if (alarmToneOn)
    {
        noTone(BUZZER_PIN);
        alarmToneOn = false;
        alarmBeepsRemaining--;
        if (alarmBeepsRemaining == 0) alarmActive = false;
    }
    else
    {
        tone(BUZZER_PIN, BUZZER_FREQUENCY_HZ);
        alarmToneOn = true;
    }
}


void printConveyorState()
{
    Serial.print("STATE,");
    Serial.print(conveyorRunning ? 1 : 0);
    Serial.print(",");
    Serial.print(physicalPressed ? 1 : 0);
    Serial.print(",");
    Serial.println(stopRevision);
}

void stopConveyor()
{
    Serial.println("DBG,CONVEYOR,STOP_REQUEST");
    conveyorRunning = false; // PUL 현재 레벨 유지: 추가 펄스를 만들지 않음
    stopRevision++;
    printConveyorState();
}

void updateEmergencyButton()
{
    if (digitalRead(ESTOP_PIN) == HIGH)
    {
        releasePending = false;
        if (!physicalPressed)
        {
            physicalPressed = true;
            Serial.println("DBG,ESTOP,D24_LOW_BUTTON_PRESSED");
            stopConveyor();
        }
    }
    else if (physicalPressed)
    {
        if (!releasePending)
        {
            releasePending = true;
            releaseStartedAt = millis();
        }
        else if (millis() - releaseStartedAt >= RELEASE_DEBOUNCE_MS)
        {
            physicalPressed = false;
            releasePending = false;
            Serial.println("DBG,ESTOP,BUTTON_RELEASED_RESTART_REQUIRED");
            printConveyorState(); // 해제만으로는 실행하지 않음
        }
    }
}

void startConveyorFromBuffer()
{
    unsigned long revision = 0;
    bool valid = startLength > 1 && startBuffer[0] == ',';
    for (int i = 1; valid && i < startLength; i++)
    {
        char c = startBuffer[i];
        if (c < '0' || c > '9' || revision > (4294967295UL - (c - '0')) / 10UL)
            valid = false;
        else
            revision = revision * 10UL + (c - '0');
    }
    if (!valid) { Serial.println("DBG,CONVEYOR,START_BAD_FORMAT"); Serial.println("ERR,BAD_START"); }
    else if (physicalPressed || digitalRead(ESTOP_PIN) == HIGH)
    {
        Serial.println("DBG,CONVEYOR,START_REJECTED_BUTTON_PRESSED");
        Serial.println("ERR,BUTTON_PRESSED");
    }
    else if (revision != stopRevision)
    {
        Serial.println("DBG,CONVEYOR,START_REJECTED_STALE_REVISION");
        Serial.println("ERR,STALE_START");
    }
    else
    {
        lastPulse = micros();
        conveyorRunning = true;
        Serial.println("DBG,CONVEYOR,START_ACCEPTED");
    }
    printConveyorState();
}

void setup()
{
    Serial.begin(115200);
    for (byte i = 0; i < BIN_COUNT; ++i)
    {
        pinMode(BIN_TRIG[i], OUTPUT);
        pinMode(BIN_ECHO[i], INPUT);
        pinMode(BIN_LED[i], OUTPUT);
        digitalWrite(BIN_TRIG[i], LOW);
        digitalWrite(BIN_LED[i], LOW);
    }
    dht.begin();
    // Fan output defaults to 50% as in the supplied standalone test sketch.
    digitalWrite(FAN_PIN, LOW);
    pinMode(FAN_PIN, OUTPUT);
    fanOutputHigh = false;
    fanPwmCycleAt = micros();
    setFan(50);
    pinMode(ESTOP_PIN, INPUT_PULLUP);
    physicalPressed = digitalRead(ESTOP_PIN) == HIGH;
    if (physicalPressed)
    {
        conveyorRunning = false; // 실물 버튼이 눌린 경우에만 시작 차단
        stopRevision++;
    }


    digitalWrite(PUL_PIN, HIGH);
    pinMode(PUL_PIN, OUTPUT);

    digitalWrite(DIR_PIN, CONVEYOR_DIRECTION);
    pinMode(DIR_PIN, OUTPUT);

    // [ALERT] 실제 컨베이어 상태로 초기 LED를 설정합니다.
    int ledOff = RGB_COMMON_ANODE ? HIGH : LOW;
    digitalWrite(RGB_RED_PIN, ledOff);
    digitalWrite(RGB_GREEN_PIN, ledOff);
    digitalWrite(RGB_BLUE_PIN, ledOff);
    pinMode(RGB_RED_PIN, OUTPUT);
    pinMode(RGB_GREEN_PIN, OUTPUT);
    pinMode(RGB_BLUE_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);
    pinMode(BUZZER_PIN, OUTPUT);
    lastLedRunning = -1;
    updateStatusLed();

    // 모터별 초기 각도 설정
    for (int i = 0; i < 5; i++)
    {
        motors[i].write(INITIAL_ANGLES[i]);
        motors[i].attach(SERVO_PINS[i]);
    }

    lastPulse = micros();

    Serial.println("DBG,BOOT,MEGA_115200");
    Serial.println("DBG,PINS,PUL_D7_DIR_D8_ESTOP_D24_DHT_D22_FAN_D23");
    Serial.println("DBG,PINS,BIN_ERROR_26_27_28_SEOUL_32_33_34_GYEONGGI_38_39_40_CHUNGCHEONG_44_45_46");
    Serial.println(physicalPressed ? "DBG,BOOT,CONVEYOR_BLOCKED_D24_LOW" : "DBG,BOOT,CONVEYOR_RUNNING_REQUESTED");
    Serial.println("DBG,HELP,SEND_QUESTION_MARK_FOR_STATE_OR_R_COMMA_REVISION_NEWLINE_TO_RESTART");
    Serial.println("READY: send 0~9");
    printConveyorState();
}

void loop()
{
    // [ESTOP] 통신/출고 상태와 관계없이 버튼을 먼저 확인
    updateEmergencyButton();
    updateFanOutput();
    updateBins();
    // [ALERT] Conveyor RGB status and nonblocking buzzer pattern.
    updateStatusLed();
    updateInspectionAlarm();

    // 1. 실행 상태일 때 기존 속도로 컨베이어 실행
    unsigned long nowMicros = micros();

    if (conveyorRunning && nowMicros - lastPulse >= PULSE_DELAY_US)
    {
        lastPulse = nowMicros;
        pulseState = !pulseState;
        digitalWrite(PUL_PIN, pulseState);
        ++stepTransitions;
    }

    // 2. 복귀 시간이 된 모터 처리
    unsigned long nowMillis = millis();

    for (int i = 0; i < 5; i++)
    {
        if (returnPending[i] &&
            nowMillis - returnStartedAt[i] >= RETURN_DELAY_MS)
        {
            motors[i].write(INITIAL_ANGLES[i]);
            returnPending[i] = false;

            Serial.print("DBG,SERVO,AUTO_RETURN,M");
            Serial.println(i + 1);
            Serial.print("DONE,M");
            Serial.println(i + 1);
        }
    }

    // [ESTOP] 잘린 실행 명령을 숫자 서보 명령으로 해석하지 않음
    if (readingStart && millis() - startReceivedAt > 250)
    {
        readingStart = false;
        discardStart = true;
    }

    // Temperature readings are informational only; never trigger conveyor controls.
    if (nowMillis - lastSensorRead >= SENSOR_INTERVAL_MS)
    {
        lastSensorRead = nowMillis;
        float humidity = dht.readHumidity();
        float temperature = dht.readTemperature();
        if (isnan(humidity) || isnan(temperature))
        {
            Serial.println("SENSOR,ERR");
            Serial.println("DBG,DHT11,READ_ERROR");
        }
        else
        {
            Serial.print("SENSOR,");
            Serial.print(temperature, 1);
            Serial.print(",");
            Serial.println(humidity, 1);
            Serial.print("DBG,DHT11,TEMP_C=");
            Serial.print(temperature, 1);
            Serial.print(",HUMIDITY_PCT=");
            Serial.println(humidity, 1);
        }
        updateFanControl(temperature, humidity);
    }

    // 2초마다 상태 및 실제 PUL 핀 전환 횟수 표시 (0이면 펄스 출력 안 함).
    // nonblocking: never add delay() in motor loop.
    if (nowMillis - lastDebugAt >= DEBUG_INTERVAL_MS)
    {
        lastDebugAt = nowMillis;
        Serial.print("DBG,STATUS,CONVEYOR=");
        Serial.print(conveyorRunning ? "RUN" : "STOP");
        Serial.print(",D24=");
        Serial.print(digitalRead(ESTOP_PIN) == LOW ? "LOW_PRESSED" : "HIGH_RELEASED");
        Serial.print(",REV=");
        Serial.print(stopRevision);
        Serial.print(",PUL_TOGGLES_2S=");
        Serial.println(stepTransitions - lastStepTransitions);
        lastStepTransitions = stepTransitions;
    }

    // 3. 시리얼 명령 처리
    if (Serial.available() > 0)
    {
        char key = Serial.read();

        // [ESTOP] !: 즉시 정지 / ?: 상태 / R,<정지번호>\n: 실행
        if (key == '!')
        {
            Serial.println("DBG,SERIAL,SOFTWARE_ESTOP_EXCLAMATION");
            discardStart = discardStart || readingStart;
            readingStart = false;
            stopConveyor();
            return;
        }
        if (key == '?')
        {
            Serial.println("DBG,SERIAL,STATUS_QUERY");
            printConveyorState();
            return;
        }
        if (discardStart)
        {
            if (key == '\n') discardStart = false;
            return;
        }
        if (readingStart)
        {
            if (key == '\n')
            {
                readingStart = false;
                startConveyorFromBuffer();
            }
            else if (key != '\r')
            {
                if (startLength < (int)sizeof(startBuffer))
                    startBuffer[startLength++] = key;
                else
                {
                    readingStart = false;
                    discardStart = true;
                    Serial.println("ERR,BAD_START");
                }
            }
            return;
        }
        if (key == 'R')
        {
            Serial.println("DBG,SERIAL,START_COMMAND_RECEIVED");
            readingStart = true;
            startLength = 0;
            startReceivedAt = millis();
            return;
        }

        // 기존 숫자 서보 명령은 그대로 유지. 줄바꿈 등은 무시
        if (key < '0' || key > '9')
        {
            return;
        }

        const MotorCommand &command = COMMANDS[key - '0'];
        int i = command.motorIndex;

        // 같은 모터가 복귀 대기 중이면 추가 명령 무시
        if (returnPending[i])
        {
            Serial.println("ERR,BUSY");
            return;
        }

        Serial.print("DBG,SERVO,COMMAND=");
        Serial.print(key);
        Serial.print(",MOTOR=");
        Serial.print(i + 1);
        Serial.print(",ANGLE=");
        Serial.println(command.angle);
        motors[i].write(command.angle);

        // [ALERT] Error-diverter command '5': three short warning beeps.
        if (key == '5') startInspectionAlarm();

        returnPending[i] = command.autoReturn;
        returnStartedAt[i] = millis();

        Serial.print("ACK,");
        Serial.println(key);
    }
}