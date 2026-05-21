# MONITOR IoT ESP32
import network
import time
import math
import ujson
import socket
import gc

from machine import Pin, PWM, I2C
import dht
import urequests

# CONFIGURACION
WIFI_SSID = "Sara"
WIFI_PASS = "3008742602"

BOT_TOKEN = "8770110509:AAH2w5e67lH2DzHt5Dv_MsNtIcUsAIfRl38"
CHAT_ID   = "8662748340"

PIN_DHT    = 4
PIN_BUZZER = 18
PIN_BOTON  = 13
PIN_SDA    = 21
PIN_SCL    = 22

MPU_ADDR   = 0x68

TEMP_MIN = 18
TEMP_MAX = 28
HUM_MIN  = 30
HUM_MAX  = 70

UMBRAL_MOV    = 1.5
UMBRAL_BRUSCO = 4.0

# HTML

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ESP32 IoT</title>
<style>
body{font-family:Arial;background:#111;color:white;text-align:center;padding:20px;}
.card{background:#222;padding:20px;margin:20px auto;border-radius:10px;width:300px;}
.valor{font-size:40px;}
.ok{color:#0f0;font-size:18px;}
.alerta{color:#f00;font-size:18px;font-weight:bold;}
.info{font-size:13px;color:#aaa;margin-top:6px;}
</style>
</head>
<body>
<h1>MONITOR IoT ESP32</h1>

<div class="card">
<h2>Temperatura</h2>
<div class="valor" id="temp">--</div>
<div id="st">--</div>
<div class="info">Rango: """ + str(TEMP_MIN) + """ &deg;C &ndash; """ + str(TEMP_MAX) + """ &deg;C</div>
</div>

<div class="card">
<h2>Humedad</h2>
<div class="valor" id="hum">--</div>
<div id="sh">--</div>
<div class="info">Rango: """ + str(HUM_MIN) + """ % &ndash; """ + str(HUM_MAX) + """ %</div>
</div>

<div class="card">
<h2>Movimiento</h2>
<div class="valor" id="mov">--</div>
<div id="sm">--</div>
<div class="info">Leve &gt; """ + str(UMBRAL_MOV) + """ g &nbsp;|&nbsp; Brusco &gt; """ + str(UMBRAL_BRUSCO) + """ g</div>
</div>

<script>
async function actualizar(){
    try{
        const r = await fetch('/datos');
        const d = await r.json();
        document.getElementById("temp").innerHTML = d.temperatura.toFixed(1)+" \u00b0C";
        document.getElementById("hum").innerHTML  = d.humedad.toFixed(1)+" %";
        document.getElementById("mov").innerHTML  = d.movimiento;
        const st = document.getElementById("st");
        const sh = document.getElementById("sh");
        const sm = document.getElementById("sm");
        st.innerHTML  = d.alarma_temp ? "ALARMA ACTIVA" : "Normal";
        st.className  = d.alarma_temp ? "alerta" : "ok";
        sh.innerHTML  = d.alarma_hum  ? "ALARMA ACTIVA" : "Normal";
        sh.className  = d.alarma_hum  ? "alerta" : "ok";
        sm.innerHTML  = d.alarma_mov  ? "ALARMA ACTIVA" : "Normal";
        sm.className  = d.alarma_mov  ? "alerta" : "ok";
    }catch(e){ console.log(e); }
}
actualizar();
setInterval(actualizar, 2000);
</script>
</body>
</html>"""

# HARDWARE
sensor_dht = dht.DHT22(Pin(PIN_DHT))
boton      = Pin(PIN_BOTON, Pin.IN, Pin.PULL_UP)
i2c        = I2C(0, sda=Pin(PIN_SDA), scl=Pin(PIN_SCL), freq=400000)
buzzer_pin = Pin(PIN_BUZZER)

# ESTADO
estado = {
    "temperatura": 0.0,
    "humedad":     0.0,
    "movimiento":  "reposo",
    "ip":          "0.0.0.0",
    "alarma_temp": False,
    "alarma_hum":  False,
    "alarma_mov":  False
}

# BUZZER
def beep():
    try:
        b = PWM(buzzer_pin, freq=2000, duty=512)
        time.sleep_ms(300)
        b.deinit()
    except Exception as e:
        print("BUZZER ERROR:", e)

# WIFI
def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("Conectando WiFi...")
    for _ in range(20):
        if wlan.isconnected():
            break
        time.sleep(1)
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        estado["ip"] = ip
        print("WiFi OK | IP:", ip)
        return ip
    print("Error WiFi")
    return None

# TELEGRAM — enviar mensaje
def telegram(msg):
    gc.collect()                        
    try:
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
        payload = ujson.dumps({"chat_id": CHAT_ID, "text": msg})
        r = urequests.post(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        print("Telegram OK:", r.status_code)
        r.close()
        gc.collect()
        return True
    except Exception as e:
        print("TELEGRAM ERROR:", e)
        gc.collect()
        return False

# MPU6050
def mpu_init():
    i2c.writeto_mem(MPU_ADDR, 0x6B, b'\x00')
    time.sleep_ms(100)

def leer_mpu():
    try:
        datos = i2c.readfrom_mem(MPU_ADDR, 0x3B, 6)
        def b2i(hi, lo):
            v = (hi << 8) | lo
            return v - 65536 if v > 32767 else v
        escala = 9.81 / 16384.0
        ax = b2i(datos[0], datos[1]) * escala
        ay = b2i(datos[2], datos[3]) * escala
        az = b2i(datos[4], datos[5]) * escala
        delta = abs(math.sqrt(ax**2 + ay**2 + az**2) - 9.81)
        if delta < UMBRAL_MOV:      return "reposo"
        elif delta < UMBRAL_BRUSCO: return "movimiento leve/moderado"
        else:                       return "brusco"
    except Exception as e:
        print("MPU ERROR:", e)
        return "error"

# LEER SENSORES + ALARMAS
def leer_sensores():
    try:
        sensor_dht.measure()
        estado["temperatura"] = sensor_dht.temperature()
        estado["humedad"]     = sensor_dht.humidity()
    except Exception as e:
        print("DHT ERROR:", e)

    estado["movimiento"] = leer_mpu()

    nueva_temp = not (TEMP_MIN <= estado["temperatura"] <= TEMP_MAX)
    nueva_hum  = not (HUM_MIN  <= estado["humedad"]     <= HUM_MAX)
    nueva_mov  = estado["movimiento"] == "brusco"

    avisos = []
    if nueva_temp and not estado["alarma_temp"]:
        avisos.append("Temperatura fuera de rango: {}C".format(estado["temperatura"]))
    if nueva_hum and not estado["alarma_hum"]:
        avisos.append("Humedad fuera de rango: {}%".format(estado["humedad"]))
    if nueva_mov and not estado["alarma_mov"]:
        avisos.append("Movimiento brusco detectado")

    if avisos:
        beep()
        telegram("ALARMA ACTIVADA\n" + "\n".join(avisos))

    estado["alarma_temp"] = nueva_temp
    estado["alarma_hum"]  = nueva_hum
    estado["alarma_mov"]  = nueva_mov

    print(estado)

# BOTON DE PANICO
ultimo_boton = 0

def verificar_boton():
    global ultimo_boton
    ahora = time.ticks_ms()
    if boton.value() == 0:
        if time.ticks_diff(ahora, ultimo_boton) > 500:
            ultimo_boton = ahora
            print("BOTON PRESIONADO")
            beep()
            telegram(
                "BOTON DE PANICO\n"
                "Temperatura: {}C\n"
                "Humedad: {}%\n"
                "Movimiento: {}".format(
                    estado["temperatura"],
                    estado["humedad"],
                    estado["movimiento"]
                )
            )
            time.sleep_ms(500)
            
# TELEGRAM POLLING — comandos T, H, M, U
ultimo_update_id = 0

def verificar_telegram():
    global ultimo_update_id
    gc.collect()
    try:
        url = (
            "https://api.telegram.org/bot" + BOT_TOKEN +
            "/getUpdates?offset=" + str(ultimo_update_id + 1) +
            "&timeout=0&limit=5"
        )
        r    = urequests.get(url)
        raw  = r.text
        r.close()
        gc.collect()

        data = ujson.loads(raw)

        for upd in data.get("result", []):
            ultimo_update_id = upd["update_id"]
            msg   = upd.get("message", {})
            texto = msg.get("text", "").strip().upper()
            print("Comando recibido:", texto)

            if texto == "T":
                telegram("Temperatura actual: {}C".format(estado["temperatura"]))
            elif texto == "H":
                telegram("Humedad actual: {}%".format(estado["humedad"]))
            elif texto == "M":
                telegram("Movimiento actual: {}".format(estado["movimiento"]))
            elif texto == "U":
                telegram(
                    "UMBRALES CONFIGURADOS\n"
                    "Temp min: {}C\n"
                    "Temp max: {}C\n"
                    "Hum min: {}%\n"
                    "Hum max: {}%\n"
                    "Mov leve: {} g\n"
                    "Mov brusco: {} g".format(
                        TEMP_MIN, TEMP_MAX,
                        HUM_MIN,  HUM_MAX,
                        UMBRAL_MOV, UMBRAL_BRUSCO
                    )
                )

    except Exception as e:
        print("POLLING ERROR:", e)
        gc.collect()

# SERVIDOR WEB
def manejar(conn):
    try:
        req = conn.recv(1024).decode()
        if "GET /datos" in req:
            body = ujson.dumps(estado)
            resp = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n\r\n" + body
            )
        else:
            resp = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html\r\n"
                "Connection: close\r\n\r\n" + HTML_PAGE
            )
        conn.sendall(resp)
    except Exception as e:
        print("WEB ERROR:", e)
    finally:
        conn.close()

def iniciar_servidor():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(5)
    s.setblocking(False)
    print("Servidor web listo")
    return s

# MAIN
def main():
    gc.collect()
    print("INICIANDO SISTEMA")

    ip = conectar_wifi()

    try:
        mpu_init()
        print("MPU6050 OK")
    except Exception as e:
        print("MPU INIT ERROR:", e)

    servidor = iniciar_servidor()

    if ip:
        time.sleep(1)                    
        telegram("Sistema iniciado correctamente")
        time.sleep_ms(800)               
        telegram("Abrir en navegador: http://" + ip)

    ultimo_sensor  = 0
    ultimo_polling = 0

    while True:
        gc.collect()
        ahora = time.ticks_ms()

     
        if time.ticks_diff(ahora, ultimo_sensor) > 2000:
            leer_sensores()
            ultimo_sensor = ahora

     
        if time.ticks_diff(ahora, ultimo_polling) > 5000:
            verificar_telegram()
            ultimo_polling = ahora

        verificar_boton()

        try:
            conn, addr = servidor.accept()
            manejar(conn)
        except:
            pass

        time.sleep_ms(10)

main()
