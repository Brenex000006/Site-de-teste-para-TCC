import requests

from utils import encryptar_mensagem, pegar_config

url_gateway = pegar_config("LBD")

def enviar_request_lambda(payload) -> int: #não modificado ainda pq n sei como o Marques vai fazer a lambda
    """
    Envia o nome da pessoa reconhecida (criptografado) para a API Lambda via HTTP POST.

    :param pessoa_reconhecida: Nome da pessoa a ser enviada para validação.
    :return: Código de status HTTP da resposta da Lambda (ex: 200, 401) ou None em caso de erro.
    """
    return None
    print(f"[INFO] Mandando para Lambda: {payload}")
    usuario_encryptado = encryptar_mensagem(payload)
    try:
        response = requests.post(url_gateway, json={"user": usuario_encryptado})
        print(f"[INFO] Resposta: {response}")
        if response.status_code == 200:
            print(f"[INFO] Usuário liberado com sucesso!")
            return response.status_code
        elif response.status_code == 401:
            print(f"[INFO] Usuário não reconhecido!")
            return response.status_code
        else:
            print(f"[INFO] Código de resposta desconhecido!")
            return response.status_code
    except Exception as e:
        print(f"[ERROR] Falhou em fazer a request: {e}")