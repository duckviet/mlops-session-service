#!/bin/bash

# --- KHỞI TẠO BIẾN TRẠNG THÁI ---
simulate_error=0
simulate_latency=0

# --- LẤY THAM SỐ ---
while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --high_api_err_rate)
      simulate_error=1
      shift # Chuyển sang tham số tiếp theo
      ;;
    --high_api_latency)
      simulate_latency=1
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--high_api_err_rate] [--high_api_latency]"
      exit 1
      ;;
  esac
done

# URL của API endpoint
API_URL="http://localhost:8000/recommendations"

echo "=================================================="
echo "Starting traffic simulation for $API_URL"
echo "Simulate Error: $simulate_error | Simulate Latency: $simulate_latency"
echo "=================================================="
echo "Press [CTRL+C] to stop."

# Vòng lặp 20 request
for i in {1..20}; do
  # --- Tạo dữ liệu ngẫu nhiên ---
  session_id=$RANDOM
  aid1=$((100000 + RANDOM % 100000))
  aid2=$((100000 + RANDOM % 100000))
  type1=$(($RANDOM % 3))
  type2=$(($RANDOM % 3))
  range=($(seq 5 25))
  topk=$(shuf -e "${range[@]}" | head -n 1)

  # --- Tạo JSON payload cơ bản ---
  base_payload=$(cat <<EOF
  {
    "session_id": $session_id,
    "current_events": [
      {"aid": $aid1, "ts": 0, "type": $type1},
      {"aid": $aid2, "ts": 1, "type": $type2}
    ],
    "top_k": $topk
  }
EOF
  )

  # --- SỬA ĐỔI PAYLOAD DỰA TRÊN CÁC CỜ ĐÃ TRUYỀN VÀO ---
  final_payload=$base_payload
  if [[ $simulate_latency -eq 1 ]]; then
    final_payload=$(echo "$final_payload" | jq '. + {"simulate_latency": true}')
  fi
  if [[ $simulate_error -eq 1 ]]; then
    final_payload=$(echo "$final_payload" | jq '. + {"simulate_error": true}')
  fi

  echo "Sending request for session_id: $session_id"

  # --- Gửi request bằng curl ---
  status_code=$(curl -s -o /dev/null -w "%{http_code}" -X 'POST' \
    "$API_URL" \
    -H 'accept: application/json' \
    -H 'Content-Type: application/json' \
    -d "$final_payload")

  echo "--> Response status code: $status_code"
  echo "--------------------------------------------------"

  # --- Tạm dừng một khoảng thời gian ngẫu nhiên ---
  sleep_time=$(echo "scale=2; 0.5 + $RANDOM/32767" | bc)
  sleep $sleep_time
done