// PrintWatch bed relay: a relay module (active HIGH) connects / disconnects the bed heater control wire.
// Relay SIG on pin 9.  Relay ON = control wire connected = bed heats.  Relay OFF = bed off.
// Wire the control wire through the relay's COM and NO contacts, so "off" (and any Uno failure) = disconnected.
// Same serial protocol as the servo version, so PrintWatch needs no changes:
//   C = heat     O = off     G = report status
// Reply to G:  P:<1880 heating | 2020 off> W:<C|O wanted> U:<uptime s> L:<ms since last command> X:<glitches>
// Safety: starts off, goes off if no command for 5 s, hardware watchdog restarts a hung board (-> off),
//         re-checks its own state every loop and goes off if anything doesn't add up.
#include <avr/wdt.h>

const int RELAY_PIN = 9;
const unsigned long TIMEOUT_MS = 5000;
const unsigned long MIN_SWITCH_MS = 2000;   // never click faster than this, whatever is asked

bool on = false;
byte onMirror = 0xA5;        // 0x5A when on, 0xA5 when off; anything else = scrambled memory
bool wantOn = false;
unsigned long lastCmd = 0;
unsigned long lastSwitch = 0;
unsigned int glitches = 0;
char buf[16];
byte len = 0;

void setRelay(bool v) {
  on = v;
  onMirror = v ? 0x5A : 0xA5;
  digitalWrite(RELAY_PIN, v ? HIGH : LOW);
}

void glitch() {
  glitches++;
  wantOn = false;
  pinMode(RELAY_PIN, OUTPUT);
  setRelay(false);
}

void setup() {
  wdt_disable();
  digitalWrite(RELAY_PIN, LOW);      // off before the pin even becomes an output
  pinMode(RELAY_PIN, OUTPUT);
  setRelay(false);
  Serial.begin(115200);
  Serial.println("BOOT open");
  lastCmd = millis();
  lastSwitch = millis();
  wdt_enable(WDTO_2S);
}

void handle(const char *c) {
  if (c[0] == 'C' && c[1] == 0) { wantOn = true; lastCmd = millis(); }
  else if (c[0] == 'O' && c[1] == 0) { wantOn = false; lastCmd = millis(); }
  else if (c[0] == 'G' && c[1] == 0) {
    unsigned long since = millis() - lastCmd;
    lastCmd = millis();
    Serial.print("P:"); Serial.print(on ? 1880 : 2020);
    Serial.print(" W:"); Serial.print(wantOn ? 'C' : 'O');
    Serial.print(" U:"); Serial.print(millis() / 1000);
    Serial.print(" L:"); Serial.print(since);
    Serial.print(" X:"); Serial.println(glitches);
  } else {
    Serial.print("ERR "); Serial.println(c);
  }
}

void loop() {
  wdt_reset();

  // self-check: state and its mirror agree, the pin is an output and matches the state
  bool pinHigh = digitalRead(RELAY_PIN) == HIGH;
  bool isOutput = (DDRB & _BV(PB1)) != 0;              // pin 9 = PB1
  if ((on && onMirror != 0x5A) || (!on && onMirror != 0xA5) || !isOutput || pinHigh != on) {
    glitch();
  }

  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') { buf[len] = 0; if (len) handle(buf); len = 0; }
    else if (len < sizeof(buf) - 1) buf[len++] = ch;
    else len = 0;
  }
  if (millis() - lastCmd > TIMEOUT_MS) wantOn = false;     // Pi went quiet -> off

  if (wantOn != on) {
    if (!wantOn) { setRelay(false); lastSwitch = millis(); }                  // turning off: always immediately
    else if (millis() - lastSwitch >= MIN_SWITCH_MS) { setRelay(true); lastSwitch = millis(); }
  }
}
