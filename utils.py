import os
from pathlib import Path

import yaml
import base64
import boto3
import cryptography
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from log_utils import log_step, get_log 

boto3_session = None

def pegar_config(tipo_config: str) -> any:
    """
    Procura configurações que devem ser secretas e não devem ficar no código

    :param tipo_config: string com o tipo de configuração que deve ser procurado
    :return: retorna uma lista ou valor para aquele tipo de configuração
    """
    path = os.path.join("Config", "config.yaml")
    configs = None
    if tipo_config == "LBD":
        with open(path, "r") as f:
            config = yaml.safe_load(f)
            configs = config["lambda"]["LAMBDA_URL"]
    return configs

def encryptar_mensagem(mensagem: str) -> str:
    """
    Criptografa uma mensagem de string usando uma chave pública RSA.

    A mensagem é codificada para bytes, criptografada usando RSA com OAEP padding
    (SHA256), e o resultado é então codificado em Base64 para fácil transmissão.

    Args:
        mensagem (str): A string a ser criptografada.

    Returns:
        str: A mensagem criptografada e codificada em Base64.
    """
    public_key = pegar_public_key()
    ciphertext = public_key.encrypt(
        mensagem.encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    mensagem_b64 = base64.b64encode(ciphertext).decode("utf-8")
    return mensagem_b64

def pegar_public_key() -> object:
    """
    Carrega uma chave pública RSA de um arquivo .pem.

    O arquivo esperado é 'RSA_Chaves/public_key.pem'.

    Returns:
        cryptography.hazmat.primitives.asymmetric.rsa.RSAPublicKey:
            O objeto da chave pública carregado.

    Raises:
        FileNotFoundError: Se o arquivo da chave pública não for encontrado.
        ValueError: Se o conteúdo do arquivo não for uma chave PEM válida.
        # Outras exceções de cryptography.hazmat.primitives.serialization podem ocorrer
    """
    with open("RSA_Chaves/public_key.pem", "rb") as f:
        public_key = serialization.load_pem_public_key(f.read())
    return public_key

def pegar_config_boto3() -> any:
    """
    Procura configurações que devem ser secretas e não devem ficar no código

    :param tipo_config: string com o tipo de configuração que deve ser procurado
    :return: retorna uma lista ou valor para aquele tipo de configuração
    """
    configs = None
    with open("Config/config.yaml", "r") as f:
        config = yaml.safe_load(f)
        configs = []
        configs.append(config["boto3_access_keys"]["ac_key"])
        configs.append(config["boto3_access_keys"]["secret_key"])
        configs.append(config["boto3_access_keys"]["region_name"])
        configs.append(config["s3_config"]["bucket"])
        configs.append(config["s3_config"]["folder"])
    return configs

def enviar_backup_s3(file, nome_user):
    lista_configs = pegar_config_boto3()
    insert_into_s3(lista_configs, file, nome_user)
    print("Inserido no S3")

def insert_into_s3(lista_configs, file, nome_user):
    file = os.path.join("static", file)
    global boto3_session
    region = lista_configs[2]
    if boto3_session is None:
        access_key = lista_configs[0]
        secret_access_key = lista_configs[1]
        boto3_session = boto3.session.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_access_key,
            region_name=region
        )
        s3 = boto3_session.client("s3", region_name=region)
    else:
        s3 = boto3_session.client("s3", region_name=region)
    bucket = lista_configs[3]
    folder = lista_configs[4]

    normalized_file = Path(file).expanduser().resolve()

    with open(normalized_file, "rb") as f:
        s3.put_object(
            Bucket=bucket,
            Key=f"{folder}backup_imagens/{nome_user}.jpg",
            Body=f,
            ContentType="image/jpeg"
        )
        print("Inserido no S3")
#quando for puxar o log pra mandar pra lambda, usar essa funcao
def log_status():
    return get_log()

def novo_step_log(step_name, status, details):
    log_step(step_name, status, details)