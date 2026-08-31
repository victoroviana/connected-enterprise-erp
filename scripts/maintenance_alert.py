#!/usr/bin/env python3
"""
Utilitário para controle de alertas de manutenção no Sollus Connected.
Uso:
  python3 scripts/maintenance_alert.py trigger 60 "Mensagem de aviso..."
  python3 scripts/maintenance_alert.py status
  python3 scripts/maintenance_alert.py cancel
"""
import sys
import os
import json
import time

def main():
    if len(sys.argv) < 2:
        print("Uso: maintenance_alert.py <trigger|cancel|status> [duracao_segundos] [mensagem]")
        sys.exit(1)

    action = sys.argv[1].lower()
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    instance_dir = os.path.join(base_dir, "instance")
    file_path = os.path.join(instance_dir, "maintenance.json")

    if action == "trigger":
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        message = sys.argv[3] if len(sys.argv) > 3 else "O sistema entrará em manutenção preventiva em instantes. Por favor, salve o seu trabalho!"
        
        os.makedirs(instance_dir, exist_ok=True)
        data = {
            "target_timestamp": time.time() + duration,
            "duration": duration,
            "message": message
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"[+] Alerta de manutenção ativado com sucesso por {duration} segundos!")
        print(f"    Arquivo: {file_path}")

    elif action == "cancel":
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print("[+] Alerta de manutenção cancelado e removido.")
            except Exception as e:
                print(f"[-] Erro ao remover: {e}")
        else:
            print("[*] Nenhum alerta de manutenção estava ativo.")

    elif action == "status":
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                remaining = int(data.get("target_timestamp", 0) - time.time())
                print(f"[STATUS] Alerta ATIVO! Tempo restante: {remaining}s | Mensagem: {data.get('message')}")
            except Exception as e:
                print(f"[-] Erro ao ler status: {e}")
        else:
            print("[STATUS] Alerta INATIVO.")

if __name__ == "__main__":
    main()
