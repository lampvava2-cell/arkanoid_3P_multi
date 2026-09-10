import asyncio
import json
import math
import random
import websockets

# 공평한 정사각형 해상도 좌표계 (500 x 500)
WIDTH = 500
HEIGHT = 500

VERSION_TITLE = "정사각형_상대터치버전5 (Square & Relative Touch)"

SLOTS = {"bottom": "BOT", "left": "BOT", "right": "BOT"}
CONNECTED_CLIENTS = {}

game_started = False
current_stage = 1
TOTAL_STAGES = 3

paddle_positions = {
    "bottom": WIDTH / 2,
    "left": HEIGHT / 2,
    "right": HEIGHT / 2
}

BALL_BASE_SPEED = 6.5
ball = {
    "x": WIDTH / 2,
    "y": HEIGHT / 2 + 100,
    "vx": 4.5,
    "vy": -4.5,
    "radius": 8
}

bricks = []

def generate_stage(stage_num):
    new_bricks = []
    brick_id = 0
    if stage_num == 1:
        # 스테이지 1: 정사각형 중앙 6x6 정방형 집중 배치
        rows, cols = 6, 6
        start_x = (WIDTH - (cols * 36)) / 2 + 3
        start_y = (HEIGHT - (rows * 22)) / 2 - 20
        for r in range(rows):
            for c in range(cols):
                new_bricks.append({"id": brick_id, "x": start_x + c * 36, "y": start_y + r * 22, "w": 30, "h": 14, "alive": True})
                brick_id += 1
    elif stage_num == 2:
        # 스테이지 2: 십자형 대칭 클러스터
        center_x, center_y = WIDTH / 2, HEIGHT / 2 - 20
        for r in range(7):
            for c in range(7):
                if r == 3 or c == 3 or (abs(r - 3) + abs(c - 3) <= 2):
                    new_bricks.append({"id": brick_id, "x": center_x - 126 + c * 36, "y": center_y - 77 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    else:
        # 스테이지 3: 8x8 외곽 요새 다이아몬드
        center_x, center_y = WIDTH / 2, HEIGHT / 2 - 20
        for r in range(8):
            for c in range(8):
                if r in [0, 7] or c in [0, 7] or (r in [3, 4] and c in [3, 4]):
                    new_bricks.append({"id": brick_id, "x": center_x - 144 + c * 36, "y": center_y - 88 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    return new_bricks

def reset_ball():
    global ball
    ball["x"] = WIDTH / 2
    ball["y"] = HEIGHT / 2 + 80
    angle = random.uniform(-0.6, 0.6)
    ball["vx"] = BALL_BASE_SPEED * math.sin(angle)
    ball["vy"] = -abs(BALL_BASE_SPEED * math.cos(angle))

bricks = generate_stage(current_stage)

def update_ai():
    ai_speed = 6.0
    if SLOTS["bottom"] == "BOT":
        tx = ball["x"]
        cx = paddle_positions["bottom"]
        paddle_positions["bottom"] += max(-ai_speed, min(ai_speed, tx - cx))
        paddle_positions["bottom"] = max(40, min(WIDTH - 40, paddle_positions["bottom"]))

    if SLOTS["left"] == "BOT":
        ty = ball["y"]
        cy = paddle_positions["left"]
        paddle_positions["left"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["left"] = max(40, min(HEIGHT - 40, paddle_positions["left"]))

    if SLOTS["right"] == "BOT":
        ty = ball["y"]
        cy = paddle_positions["right"]
        paddle_positions["right"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["right"] = max(40, min(HEIGHT - 40, paddle_positions["right"]))

async def broadcast_lobby():
    slots_info = {}
    for role, occ in SLOTS.items():
        slots_info[role] = "BOT" if occ == "BOT" else "USER"
    payload = json.dumps({
        "type": "lobby_state",
        "title": VERSION_TITLE,
        "slots": slots_info,
        "game_started": game_started,
        "stage": current_stage
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except:
            pass

def enforce_speed_and_angle(vx, vy):
    current_speed = math.hypot(vx, vy)
    if current_speed == 0:
        return BALL_BASE_SPEED, -BALL_BASE_SPEED
    scale = BALL_BASE_SPEED / current_speed
    return vx * scale, vy * scale

async def game_loop():
    global game_started, current_stage, bricks, ball
    P_LEN = 70  # 정사각형에 맞춘 패들 균등 길이

    while True:
        if game_started:
            update_ai()

            sub_steps = 2
            step_vx = ball["vx"] / sub_steps
            step_vy = ball["vy"] / sub_steps

            for _ in range(sub_steps):
                ball["x"] += step_vx
                ball["y"] += step_vy

                # 1. 상단 천장 반사
                if ball["y"] - ball["radius"] <= 10:
                    ball["y"] = 10 + ball["radius"]
                    ball["vy"] = abs(ball["vy"])
                    step_vy = abs(step_vy)

                # 2. 하단 패들 충돌
                if ball["y"] + ball["radius"] >= HEIGHT - 22:
                    pad_x = paddle_positions["bottom"]
                    if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                        offset = (ball["x"] - pad_x) / (P_LEN / 2)
                        rebound_angle = offset * (math.pi / 3)
                        ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                    elif ball["y"] > HEIGHT + 30:
                        reset_ball()
                        break

                # 3. 좌측 패들 충돌 (상향 바이어스)
                if ball["x"] - ball["radius"] <= 22:
                    pad_y = paddle_positions["left"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        adjusted_offset = max(-1.0, min(1.0, offset - 0.25))
                        rebound_angle = adjusted_offset * (math.pi / 3.2)
                        
                        ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        
                        if abs(ball["vy"]) < 2.5:
                            ball["vy"] = -2.8 if offset <= 0 else 2.8
                        ball["vx"], ball["vy"] = enforce_speed_and_angle(ball["vx"], ball["vy"])
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                    elif ball["x"] < -30:
                        reset_ball()
                        break

                # 4. 우측 패들 충돌 (상향 바이어스)
                if ball["x"] + ball["radius"] >= WIDTH - 22:
                    pad_y = paddle_positions["right"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        adjusted_offset = max(-1.0, min(1.0, offset - 0.25))
                        rebound_angle = adjusted_offset * (math.pi / 3.2)
                        
                        ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        
                        if abs(ball["vy"]) < 2.5:
                            ball["vy"] = -2.8 if offset <= 0 else 2.8
                        ball["vx"], ball["vy"] = enforce_speed_and_angle(ball["vx"], ball["vy"])
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                    elif ball["x"] > WIDTH + 30:
                        reset_ball()
                        break

                # 5. 벽돌 충돌 판정
                r = ball["radius"]
                for b in bricks:
                    if b["alive"]:
                        if (ball["x"] + r >= b["x"] and ball["x"] - r <= b["x"] + b["w"] and
                            ball["y"] + r >= b["y"] and ball["y"] - r <= b["y"] + b["h"]):
                            b["alive"] = False
                            prev_x = ball["x"] - step_vx
                            prev_y = ball["y"] - step_vy
                            if prev_x + r <= b["x"] or prev_x - r >= b["x"] + b["w"]:
                                ball["vx"] = -ball["vx"]
                                step_vx = -step_vx
                            else:
                                ball["vy"] = -ball["vy"]
                                step_vy = -step_vy
                            break

            # 스테이지 완료
            if sum(1 for b in bricks if b["alive"]) == 0:
                current_stage = (current_stage % TOTAL_STAGES) + 1
                bricks = generate_stage(current_stage)
                reset_ball()

            # 브로드캐스트
            bot_list = [role for role, occ in SLOTS.items() if occ == "BOT"]
            payload = json.dumps({
                "type": "game_update",
                "ball": ball,
                "paddles": paddle_positions,
                "bot_slots": bot_list,
                "stage": current_stage,
                "bricks": [b["id"] for b in bricks if not b["alive"]]
            })
            for ws in list(CONNECTED_CLIENTS.keys()):
                try:
                    await ws.send(payload)
                except:
                    pass

        await asyncio.sleep(0.016)

async def handler(websocket):
    CONNECTED_CLIENTS[websocket] = {"role": None}
    await broadcast_lobby()

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "select_role":
                role = data.get("role")
                for r, occ in SLOTS.items():
                    if occ == websocket:
                        SLOTS[r] = "BOT"
                if role in SLOTS and (SLOTS[role] == "BOT" or SLOTS[role] == websocket):
                    SLOTS[role] = websocket
                    CONNECTED_CLIENTS[websocket]["role"] = role
                await broadcast_lobby()

            elif msg_type == "start_game":
                global game_started, current_stage, bricks
                current_stage = 1
                bricks = generate_stage(current_stage)
                reset_ball()
                game_started = True
                init_payload = json.dumps({
                    "type": "game_start",
                    "stage": current_stage,
                    "bricks": bricks
                })
                for ws in list(CONNECTED_CLIENTS.keys()):
                    await ws.send(init_payload)

            elif msg_type == "move":
                role = CONNECTED_CLIENTS[websocket]["role"]
                if role and game_started:
                    # 정사각형 범위 내로 제한
                    max_limit = WIDTH - 35 if role == "bottom" else HEIGHT - 35
                    paddle_positions[role] = max(35, min(max_limit, data["pos"]))

    except websockets.ConnectionClosed:
        pass
    finally:
        for r, occ in SLOTS.items():
            if occ == websocket:
                SLOTS[r] = "BOT"
        CONNECTED_CLIENTS.pop(websocket, None)
        await broadcast_lobby()

async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    print(f"[{VERSION_TITLE}] 서버 가동 중 (500x500)...")
    await asyncio.gather(server.wait_closed(), game_loop())

if __name__ == "__main__":
    asyncio.run(main())
