// PrintWatch bed servo: connects / disconnects the bed heater control wire.
// Servo signal on pin 9.  1880 us = closed (bed heats), 2020 us = open (bed off).
// Serial 115200, one command per line from the Pi:
//   C  = close (heat)     O = open (off)     G = report status
// Reply to G:  P:<us now> W:<C|O wanted> U:<uptime s> L:<ms since last command> X:<glitches seen>
// Pin 9 is driven by Timer1 hardware PWM (50 Hz, 0.5 us steps), no Servo library needed.
// Safety:
//  - starts open, goes open if no command for 5 s, hardware watchdog restarts a hung board (-> open)
//  - v2: the pulse width can ONLY ever be 1880..2020 us. Every loop the position, its mirror copy and
//    the Timer1 registers are checked; anything out of range or mismatched (e.g. a power dip
//    scrambling memory) snaps straight to open and counts a glitch (X).
#include <avr/wdt.h>

const int SERVO_PIN = 9;
const int US_CLOSED = 1880;
const int US_OPEN = 2020;
const unsigned long TIMEOUT_MS = 5000;
const unsigned long STEP_MS = 8;      // slow move: 1 us every 8 ms (~1.1 s end to end), low current

int posUs = US_OPEN;
int posMirror = ~US_OPEN;             // always ~posUs; a mismatch means memory got scrambled
bool wantClosed = false;
unsigned long lastCmd = 0;
unsigned long lastStep = 0;
unsigned int glitches = 0;
char buf[16];
byte len = 0;

void timerSetup() {
  // Timer1: fast PWM mode 14, TOP = ICR1, prescaler 8 -> 0.5 us per tick, 20 ms period
  TCCR1A = 0; TCCR1B = 0; TCNT1 = 0;
  ICR1 = 39999;
  OCR1A = US_OPEN * 2;
  TCCR1A = _BV(COM1A1) | _BV(WGM11);
  TCCR1B = _BV(WGM13) | _BV(WGM12) | _BV(CS11);
}

void setPos(int us) {
  if (us < US_CLOSED || us > US_OPEN) us = US_OPEN;   // never anything outside the two positions
  posUs = us;
  posMirror = ~us;
  OCR1A = (unsigned int)us * 2;
}

void glitch() {
  glitches++;
  wantClosed = false;
  timerSetup();
  setPos(US_OPEN);
}

void setup() {
  wdt_disable();
  timerSetup();                        // first pulse is already "open"
  pinMode(SERVO_PIN, OUTPUT);
  setPos(US_OPEN);
  Serial.begin(115200);
  Serial.println("BOOT open");
  lastCmd = millis();
  wdt_enable(WDTO_2S);
}

void handle(const char *c) {
  if (c[0] == 'C' && c[1] == 0) { wantClosed = true; lastCmd = millis(); }
  else if (c[0] == 'O' && c[1] == 0) { wantClosed = false; lastCmd = millis(); }
  else if (c[0] == 'G' && c[1] == 0) {
    unsigned long since = millis() - lastCmd;
    lastCmd = millis();
    Serial.print("P:"); Serial.print(posUs);
    Serial.print(" W:"); Serial.print(wantClosed ? 'C' : 'O');
    Serial.print(" U:"); Serial.print(millis() / 1000);
    Serial.print(" L:"); Serial.print(since);
    Serial.print(" X:"); Serial.println(glitches);
  } else {
    Serial.print("ERR "); Serial.println(c);
  }
}

void loop() {
  wdt_reset();

  // self-check: position sane, mirror matches, timer registers as set up
  unsigned int ocr = OCR1A;
  if (posUs < US_CLOSED || posUs > US_OPEN || posMirror != ~posUs ||
      ICR1 != 39999 || ocr != (unsigned int)posUs * 2 ||
      TCCR1A != (_BV(COM1A1) | _BV(WGM11)) || TCCR1B != (_BV(WGM13) | _BV(WGM12) | _BV(CS11))) {
    glitch();
  }

  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') { buf[len] = 0; if (len) handle(buf); len = 0; }
    else if (len < sizeof(buf) - 1) buf[len++] = ch;
    else len = 0;                       // too long: drop it
  }
  if (millis() - lastCmd > TIMEOUT_MS) wantClosed = false;   // Pi went quiet -> off

  int target = wantClosed ? US_CLOSED : US_OPEN;
  if (posUs != target && millis() - lastStep >= STEP_MS) {
    lastStep = millis();
    setPos(posUs + ((target > posUs) ? 1 : -1));
  }
}
