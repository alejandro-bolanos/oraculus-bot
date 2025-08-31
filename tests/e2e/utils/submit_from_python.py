import io

import pandas as pd
import zulip


def submit_to_oraculus(positive_ids, name, bot_email, user_email, api_key, site):
    """
    Envía lista de IDs positivos a OraculusBot
    Args:
        positive_ids: Lista o set de IDs predichos como positivos
        name: Nombre del modelo/envío
        bot_email: Email del bot de Zulip
        user_email: Tu email de Zulip
        api_key: Tu API key de Zulip
        site: URL del sitio Zulip
    """
    # Crear DataFrame con una columna
    df = pd.DataFrame(positive_ids, columns=['id'])

    client = zulip.Client(email=user_email, api_key=api_key, site=site)

    # Convertir a CSV bytes
    csv_data = io.BytesIO(df.to_csv(index=False, header=False).encode())
    csv_data.name = f"{name}.csv"
    # Subir archivo
    upload = client.upload_file(csv_data)
    if upload['result'] != 'success':
        raise Exception(f"Upload error: {upload}")

    # Enviar mensaje con archivo adjunto
    msg = client.send_message({
        'type': 'private',
        'to': bot_email,
        'content': f'submit {name}\n[{name}.csv]({upload["uri"]})'
    })
    if msg['result'] != 'success':
        raise Exception(f"Send error: {msg}")

    print(f"✅ Modelo '{name}' enviado exitosamente!")

if __name__ == "__main__":
    pass
