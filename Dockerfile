FROM python:3.11-slim

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    pkg-config \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Actualizar pip
RUN pip install --upgrade pip setuptools wheel

# Establecer directorio de trabajo
WORKDIR /app

# Copiar requirements para Linux
COPY requirements.txt ./requirements.txt

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de archivos del proyecto
COPY . .

# Compilar la aplicación
RUN flet pack main.py \
    --name "Gestor-La-Loba" \
    --add-data "assets:assets" \
    --add-data "components:components" \
    --add-data "modules:modules" \
    --add-data "pages:pages" \
    --add-data "utilities:utilities" \
    --add-data "data:data" \
    --add-data "router:router"

# El ejecutable estará en /app/dist/
CMD ["./dist/Gestor-La-Loba"]