import os
import json
import threading
import time

from lambda_utils.Lambda_wrapper import enviar_request_lambda

change_buffer = {
    "cadUsuario" : "cad_teste",
    "imagens": {"adicionar": [], "deletar": []},
    "usuarios": {"adicionar": [], "deletar": []}
}
buffer_lock = threading.Lock()
last_update_time = time.time()
DEBOUNCE_SECONDS = 60
PERSISTENT_FILE = os.path.join("static","sync_buffer.json")

def carregar_buffer():
    global change_buffer
    if os.path.exists(PERSISTENT_FILE):
        try:
            with open(PERSISTENT_FILE, 'r') as f:
                loaded = json.load(f)
                for tipo in ["imagens", "usuarios"]:
                    for acao in ["adicionar", "deletar"]:
                        change_buffer[tipo][acao] = list(set(loaded.get(tipo, {}).get(acao, [])))
            print("Buffer carregado do disco.")
        except Exception as e:
            print("Erro ao carregar buffer:", e)

def debounce_worker():
    while True:
        time.sleep(5)
        now = time.time()
        with buffer_lock:
            if now - last_update_time >= DEBOUNCE_SECONDS and not buffer_esta_vazio():
                if not buffer_esta_vazio():
                    print(change_buffer)
                    enviar_request_lambda(change_buffer)

def registrar_alteracao_buffer(tipo, acao, valor):
    global last_update_time
    with buffer_lock:
        if isinstance(valor, list):
            change_buffer[tipo][acao].extend(valor)
        else:
            change_buffer[tipo][acao].append(valor)
        # Deduplicar
        change_buffer[tipo][acao] = list(set(change_buffer[tipo][acao]))
        last_update_time = time.time()
        salvar_buffer_em_disco()

def salvar_buffer_em_disco():
    try:
        with open(PERSISTENT_FILE, 'w') as f:
            json.dump(change_buffer, f, indent=4)
    except Exception as e:
        print("Erro ao salvar buffer no disco:", e)

def buffer_esta_vazio():
    with buffer_lock:
        for tipo in change_buffer:
            for acao in change_buffer[tipo]:
                if change_buffer[tipo][acao]:  # non-empty list
                    return False
    return True