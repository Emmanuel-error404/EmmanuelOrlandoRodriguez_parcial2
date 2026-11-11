#!/usr/bin/env python3
import getpass
import re
import sys
from datetime import datetime
from pathlib import Path

import pexpect

HOST = "10.20.25.1"
USER = "emmanuel"
PROMPT = r"(?m)^R1#\s*$"

SSH_OPTIONS = [
    "-oKexAlgorithms=+diffie-hellman-group14-sha1",
    "-oHostKeyAlgorithms=+ssh-rsa",
    "-oCiphers=+aes128-cbc",
]


def obtener_configuracion():
    conexion = pexpect.spawn(
        "ssh",
        SSH_OPTIONS + [f"{USER}@{HOST}"],
        encoding="utf-8",
        timeout=60,
    )

    try:
        conexion.expect(r"(?i)password:")
        conexion.sendline(getpass.getpass("Contraseña SSH de R1: "))
        conexion.expect(PROMPT, timeout=30)

        # Ajusta solo la paginación de esta sesión SSH.
        conexion.sendline("terminal length 0")
        conexion.expect(PROMPT, timeout=15)

        # Consulta de solo lectura; no modifica la configuración.
        conexion.sendline("show running-config")
        conexion.expect(PROMPT, timeout=90)
        configuracion = conexion.before

        conexion.sendline("exit")
        conexion.close()
        return configuracion

    except pexpect.TIMEOUT:
        conexion.close(force=True)
        raise RuntimeError(
            "Tiempo agotado. Revisa la conexión SSH, el usuario y la contraseña."
        )
    except pexpect.EOF:
        conexion.close()
        raise RuntimeError(
            "La sesión SSH se cerró antes de obtener la configuración."
        )


def bloques_vty(configuracion):
    encontrados = []
    bloque_actual = None

    for linea in configuracion.splitlines():
        inicio = re.match(r"^line\s+(.+)$", linea.strip())

        if inicio:
            if bloque_actual is not None:
                encontrados.append(bloque_actual)

            nombre = inicio.group(1)
            if nombre.lower().startswith("vty"):
                bloque_actual = {"nombre": nombre, "lineas": []}
            else:
                bloque_actual = None
        elif bloque_actual is not None:
            bloque_actual["lineas"].append(linea.strip())

    if bloque_actual is not None:
        encontrados.append(bloque_actual)

    return encontrados


def auditar(configuracion):
    vty = bloques_vty(configuracion)

    ssh_v2 = bool(
        re.search(r"(?mi)^\s*ip ssh version 2\s*$", configuracion)
    )

    solo_ssh_en_vty = bool(vty) and all(
        any(linea.lower() == "transport input ssh" for linea in bloque["lineas"])
        for bloque in vty
    )

    timeout_correcto = bool(vty)
    for bloque in vty:
        valores = [
            re.match(r"exec-timeout\s+(\d+)\s+(\d+)", linea, re.I)
            for linea in bloque["lineas"]
        ]
        valores = [valor for valor in valores if valor]

        if not valores:
            timeout_correcto = False
            break

        minutos, segundos = map(int, valores[0].groups())
        total_segundos = minutos * 60 + segundos

        if total_segundos == 0 or total_segundos > 600:
            timeout_correcto = False
            break

    usuario_con_secret = bool(
        re.search(
            r"(?mi)^username\s+\S+.*\bsecret\s+\d+\s+\S+",
            configuracion,
        )
    )

    return [
        ("SSH versión 2", ssh_v2),
        ("VTY acepta solo SSH", solo_ssh_en_vty),
        ("VTY tiene exec-timeout de hasta 10 minutos", timeout_correcto),
        ("Existe un usuario local configurado con secret", usuario_con_secret),
    ]


def main():
    try:
        configuracion = obtener_configuracion()
        resultados = auditar(configuracion)
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}")
        sys.exit(1)

    ahora = datetime.now().astimezone()
    fecha = ahora.strftime("%Y%m%d_%H%M%S")
    archivo = Path(f"informe_cis_R1_{fecha}.txt")

    lineas = [
        "Informe de auditoría de configuración Cisco IOS",
        f"Dispositivo: R1 ({HOST})",
        f"Fecha local: {ahora.isoformat(timespec='seconds')}",
        "",
        "Modo: solo lectura. No se aplicaron reglas ni cambios.",
        "",
        "Resultados:",
    ]

    for nombre, aprobado in resultados:
        estado = "CUMPLE" if aprobado else "REVISAR"
        lineas.append(f"[{estado}] {nombre}")

    archivo.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))
    print(f"\nInforme guardado en: {archivo.resolve()}")


if __name__ == "__main__":
    main()
