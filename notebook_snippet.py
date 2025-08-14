import pandas as pd
import io
import zulip

def submit_to_oraculus(df, name, bot_email, user_email, api_key, site):
    """Envía DataFrame a OraculusBot (2 cols: id, pred binaria)"""
    if df.shape[1] != 2 or not all(p in [0,1] for p in df.iloc[:,1]):
        raise ValueError("2 columnas requeridas, predicciones deben ser 0/1")
    
    client = zulip.Client(email=user_email, api_key=api_key, site=site)
    csv_data = io.BytesIO(df.to_csv(index=False, header=False).encode())
    
    upload = client.upload_file(csv_data, filename=f"{name}.csv")
    if upload['result'] != 'success': raise Exception(f"Upload error: {upload}")
    
    msg = client.send_message({
        'type': 'private', 'to': bot_email,
        'content': f'submit {name}\n[{name}.csv]({upload["uri"]})'
    })
    if msg['result'] != 'success': raise Exception(f"Send error: {msg}")
    
    print(f"✅ '{name}' enviado!")

# Uso:
# submit_to_oraculus(df, "modelo_v1", "bot@org.zulipchat.com", 
#                   "you@email.com", "your-key", "https://org.zulipchat.com")