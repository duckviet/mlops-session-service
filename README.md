<!-- Banner -->
<p align="center">
  <a href="https://www.uit.edu.vn/" title="Trường Đại học Công nghệ Thông tin" style="border: none;">
    <img src="https://i.imgur.com/WmMnSRt.png" alt="Trường Đại học Công nghệ Thông tin | University of Information Technology">
  </a>
</p>

# Group members
| STT    | MSSV          | Họ và Tên              |  Email                  |
| ------ |:-------------:| ----------------------:|-------------------------:
| 1      | 22520273      | Nguyễn Viết Đức        |22520273@gm.uit.edu.vn   |
| 2      | 22520459      | Đoàn Văn Hoàng         |22520459@gm.uit.edu.vn   |
| 3      | 22520862      | Huỳnh Nhật Minh        |22520862@gm.uit.edu.vn   |

# Session-Service

Session-based recommendation API built with FastAPI, Polars, and LightGBM.  

## Repository Main Structure

```
.
├── Dockerfile
├── docker-compose.yml
├── main.py
├── process_pipeline.py     #  Polars feature‐engineering pipeline
├── requirements.txt
├── model/
│   └── lgbm_ranker.joblib  # pre‐trained LightGBM ranking model
└── README.md
```


<h2 align="center">LAB2</h2>


## Quickstart

### How to install

### 1. Local Python Run

```bash
# create new venv(python 3.10) (if needed)

## Build python 3.10 (if you don't have)
sudo apt update
sudo apt install -y wget build-essential libssl-dev zlib1g-dev \
  libncurses5-dev libbz2-dev libreadline-dev libsqlite3-dev curl \
  libffi-dev liblzma-dev tk-dev
cd /usr/src
sudo wget https://www.python.org/ftp/python/3.10.13/Python-3.10.13.tgz
sudo tar xzf Python-3.10.13.tgz
cd Python-3.10.13
sudo ./configure --enable-optimizations
sudo make -j$(nproc)
sudo make altinstall

## create new virtual venv avoid conflicts
python3.10 -m venv .venv
source .venv/bin/activate

# (from /usr/src/Python-3.10.13)
cd ~/mlops-session-service 

# Install deps
pip install -r requirements.txt

# then start Uvicorn
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser at `http://127.0.0.1:8000/docs` to test the API.

### 2. Docker & Compose

```bash
# build service images
docker-compose build

# launch app
docker-compose up -d

# follow logs
docker-compose logs -f app
```

Swagger UI: `http://127.0.0.1:8000/docs` to test the API.

## 3. DockerHub
```bash
# Pull docker image 
docker pull 22520273/session-service-app

# Run docker
docker run -d -p 8888:8000 --name session_service 22520273/session-service-app:latest

# Go to `http://localhost:8888/docs` to test the API

# Check run
docker ps

# Check log  --name
docker logs session_service

```
![image](https://github.com/user-attachments/assets/e628b154-090f-4304-a126-f7639a282387)

---
### DEMO DOCKER SERVING
[![Watch the video](demo.gif)]


## API Usage

### Endpoint

POST `/recommendations`

Request model:
```json
{
  "session_id": 12345,
  "current_events": [
    {"aid": 101, "ts": 1661119200, "type": 0},
    {"aid": 202, "ts": 1661119300, "type": 1}
  ],
  "top_k": 5
}
```

- `session_id` (int): unique session identifier  
- `current_events` (array of `{aid, ts, type}`): user's past interactions  
- `top_k` (int, default 20): number of recommendations to return

Response model:
```json
{
  "session_id": 12345,
  "recommendations": [
    {"aid": 54321, "score": 1.2345},
    {"aid": 98765, "score": 1.1234},
    …
  ]
}
```

<h2 align="center">LAB3</h2>

## System architecture

```mermaid
graph TD
    subgraph "User Interaction"
        U[User/Developer]
        TG[./traffic_generator.sh]
    end

    subgraph "Application Stack"
        APP[FastAPI App]
        KAFKA[Kafka]
    end

    subgraph "Monitoring & Logging Stack"
        PROM[Prometheus]
        GRA[Grafana]
        LOKI[Loki]
        PT[Promtail]
        AM[Alertmanager]
        NE[Node Exporter]
    end

    subgraph "Notification Channel"
        SLACK[Slack]
    end

    U -- Runs --> TG
    TG -- HTTP Requests --> APP
    APP -- Produces Events --> KAFKA

    PROM -- Scrapes Metrics --> APP
    PROM -- Scrapes Metrics --> NE
    PT -- Tails Logs --> Docker & Syslog
    PT -- Pushes Logs --> LOKI

    PROM -- Sends Alerts --> AM
    AM -- Sends Notifications --> SLACK

    GRA -- Queries Metrics --> PROM
    GRA -- Queries Logs --> LOKI
    U -- Views Dashboards --> GRA
```

- Prometheus: Collect and store Metrics over time.
- Grafana: Visiting Metrics from Prometheus and Logs from Loki on Dashboard.
- Loki & Promtail: Log synthesis system, log log collection from all containers and system files.
- Alertmanager: processing and sending warnings (using Slack in this Lab).
- Node Exporter: Provides Metrics of the server's resources (CPU, RAM, Disk, Network).

### Launch a complete system

Monitoring services have been built in docker-compose.yml.

```bash
# Build image for the first time
docker-compose build

# Run the entire system (including monitoring stack)
docker-compose up -d

# Check for docker up success
docker-compose ps

# Follow the log of a specific service 
docker-compose logs
```

### Access services

Access the monitoring system user interfaces after lauch success

| Services | URL | Default account | Purpose |
| :--- | :--- | :--- | :--- |
| **Grafana** | `http://localhost:3002` | `admin` / `admin` | Visualization of Metrics and Logs |
| **Prometheus** | `http://localhost:9090` | N/A | See targets state, query metrics |
| **Alertmanager** | `http://localhost:9093` | N/A | See the status of warnings |
| **Kafdrop** | `http://localhost:9000` | N/A | See the messages in kafka topics |
| **API Docs** | `http://localhost:8000/docs`| N/A | Giao diện Swagger UI của API (like Lab2) |

---

### Simulate scenarios for testing

Use the upgraded `traffic_generator.sh` script to test the monitoring and alerting system.

| Script | Execution command | Expected result |
| :--- | :--- | :--- |
| **Working fine** | `./traffic_generator.sh` | Requests return code 200. Dashboard shows low latency and no errors. |
| **High API latency** | `./traffic_generator.sh --scenario=latency` | Requests return code 200. API Latency graph on Grafana spikes. |
| **High API error rate** | `./traffic_generator.sh --scenario=error` | Requests return code 500. Error Rate graph on Grafana spikes to 100%. **Received alert on Slack** after about 1 minute. |

## Demo
## Grafana Dashboard
![image](https://github.com/user-attachments/assets/38a2bbc4-6c06-4c56-98b8-f5f6e9a7af66)

[**Checkout our Grafana Dashboard - share in snapshots.raintank**](https://snapshots.raintank.io/dashboard/snapshot/DyAhJcVv5TTcIwPQxPZabgAMAY1mOWY4?orgId=0)

## Video demo 


    


