# Cómo crear usuarios en Zulip (instancia Docker)

## Paso 1: Dar permisos de administrador al usuario (requerido)

Antes de poder crear usuarios vía API, el usuario que hace la solicitud debe tener rol de administrador del realm y tener permisos de creación.

Ejecuta este comando dentro del contenedor Zulip:

```bash
manage.py change_user_role <email> admin -r <realm id>
manage.py change_user_role <email> can_create_users -r <realm id>
```

## Paso 2: Crear un nuevo usuario mediante la API
Ejecutar la siguiente secuencia
```bash
chmod +x create_users.zsh
./create_users.zsh <user_email1>=<user_name1> <user_email2>=<user_name2> <user_email3>=<user_name3>
```

Devolverá un json con la info de los usuarios creados y su API KEY.
