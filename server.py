import asyncio
import json
import math
import os
import random
import websockets

WIDTH = 500
HEIGHT = 500

VERSION_TITLE = "무수반사스어버전8 (Angle Forced & Score System)"

SLOTS = {"bottom": None, "left": None, "right": None}
PLAYER_NAMES = {"bottom": "BOT", "left": "BOT", "right": "BOT"}
SCORES = {"bottom": 0, "left": 0, "right": 0}
CONNECTED_CLIENTS = {}

game_started = False
current_stage = 1
TOTAL_STAGES = 3
last_hitter = None

paddle_positions = {
    "bottom": WIDTH / 2,
    "left": HEIGHT / 2,
    "right": HEIGHT / 2
}

BALL_BASE_SPEED = 6.8
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
    center_x, center_y = WIDTH / 2, HEIGHT / 2 - 20
    if stage_num == 1:
        rows, cols = 6, 6
        start_x = (WIDTH - (cols * 36)) / 2 + 3
        start_y = (HEIGHT - (rows * 22)) / 2 - 20
        for r in range(rows):
            for c in range(cols):
                new_bricks.append({"id": brick_id, "x": start_x + c * 36, "y": start_y + r * 22, "w": 30, "h": 14, "alive": True})
                brick_id += 1
    elif stage_num == 2:
        for r in range(7):
            for c in range(7):
                if r == 3 or c == 3 or (abs(r - 3) + abs(c - 3) <= 2):
                    new_bricks.append({"id": brick_id, "x": center_x - 126 + c * 36, "y": center_y - 77 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    else:
        for r in range(8):
            for c in range(8):
                if r in [0, 7] or c in [0, 7] or (r in [3, 4] and c in [3, 4]):
                    new_bricks.append({"id": brick_id, "x": center_x - 144 + c * 36, "y": center_y - 88 + r * 22, "w": 30, "h": 14, "alive": True})
                    brick_id += 1
    return new_bricks

def reset_ball():
    global ball, last_hitter
    ball["x"] = WIDTH / 2
    ball["y"] = HEIGHT / 2 + 80
    angle = random.choice([-1, 1]) * random.uniform(0.35, 0.75)
    ball["vx"] = BALL_BASE_SPEED * math.sin(angle)
    ball["vy"] = -abs(BALL_BASE_SPEED * math.cos(angle))
    last_hitter = None

bricks = generate_stage(current_stage)

def update_ai():
    ai_speed = 6.2
    if SLOTS["bottom"] is None:
        tx = ball["x"]
        cx = paddle_positions["bottom"]
        paddle_positions["bottom"] += max(-ai_speed, min(ai_speed, tx - cx))
        paddle_positions["bottom"] = max(40, min(WIDTH - 40, paddle_positions["bottom"]))

    if SLOTS["left"] is None:
        ty = ball["y"]
        cy = paddle_positions["left"]
        paddle_positions["left"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["left"] = max(40, min(HEIGHT - 40, paddle_positions["left"]))

    if SLOTS["right"] is None:
        ty = ball["y"]
        cy = paddle_positions["right"]
        paddle_positions["right"] += max(-ai_speed, min(ai_speed, ty - cy))
        paddle_positions["right"] = max(40, min(HEIGHT - 40, paddle_positions["right"]))

async def broadcast_lobby():
    slots_info = {}
    for role in ["bottom", "left", "right"]:
        ws = SLOTS[role]
        slots_info[role] = {"type": "BOT" if ws is None else "USER", "name": PLAYER_NAMES[role]}

    waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info.get("state") == "waiting"]

    payload = json.dumps({
        "type": "lobby_state",
        "title": VERSION_TITLE,
        "slots": slots_info,
        "scores": SCORES,
        "game_started": game_started,
        "waiting_users": waiting_users,
        "stage": current_stage
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except:
            pass

def enforce_non_vertical(vx, vy, base_dir="y"):
    min_component = 2.4
    if base_dir == "y":
        if abs(vx) < min_component:
            vx = min_component if vx >= 0 else -min_component
    else:
        if abs(vy) < min_component:
            vy = min_component if vy >= 0 else -min_component

    current_speed = math.hypot(vx, vy)
    scale = BALL_BASE_SPEED / current_speed
    return vx * scale, vy * scale

async def game_loop():
    global game_started, current_stage, bricks, ball, last_hitter
    P_LEN = 70

    while True:
        if game_started:
            update_ai()

            sub_steps = 4
            step_vx = ball["vx"] / sub_steps
            step_vy = ball["vy"] / sub_steps

            for _ in range(sub_steps):
                ball["x"] += step_vx
                ball["y"] += step_vy

                # 1. 상단 천장 반사
                if ball["y"] - ball["radius"] <= 10:
                    ball["y"] = 10 + ball["radius"]
                    ball["vy"] = abs(ball["vy"])
                    ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "y")
                    step_vx = ball["vx"] / sub_steps
                    step_vy = ball["vy"] / sub_steps

                # 2. 하단 패들 충돌
                if ball["y"] + ball["radius"] >= HEIGHT - 22:
                    pad_x = paddle_positions["bottom"]
                    if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                        ball["y"] = HEIGHT - 22 - ball["radius"]
                        offset = (ball["x"] - pad_x) / (P_LEN / 2)
                        if abs(offset) < 0.22:
                            offset = 0.35 if offset >= 0 else -0.35

                        rebound_angle = offset * (math.pi / 2.8)
                        ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "y")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        last_hitter = "bottom"
                    elif ball["y"] > HEIGHT + 30:
                        SCORES["bottom"] = max(0, SCORES["bottom"] - 200)
                        reset_ball()
                        break

                # 3. 좌측 패들 충돌
                if ball["x"] - ball["radius"] <= 22:
                    pad_y = paddle_positions["left"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["x"] = 22 + ball["radius"]
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        if abs(offset) < 0.22:
                            offset = -0.35

                        adj_offset = max(-1.0, min(1.0, offset - 0.2))
                        rebound_angle = adj_offset * (math.pi / 2.9)
                        ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "x")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        last_hitter = "left"
                    elif ball["x"] < -30:
                        SCORES["left"] = max(0, SCORES["left"] - 200)
                        reset_ball()
                        break

                # 4. 우측 패들 충돌
                if ball["x"] + ball["radius"] >= WIDTH - 22:
                    pad_y = paddle_positions["right"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["x"] = WIDTH - 22 - ball["radius"]
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        if abs(offset) < 0.22:
                            offset = -0.35

                        adj_offset = max(-1.0, min(1.0, offset - 0.2))
                        rebound_angle = adj_offset * (math.pi / 2.9)
                        ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "x")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        last_hitter = "right"
                    elif ball["x"] > WIDTH + 30:
                        SCORES["right"] = max(0, SCORES["right"] - 200)
                        reset_ball()
                        break

                # 5. 벽돌 충돌 및 점수
                r = ball["radius"]
                for b in bricks:
                    if not b["alive"]:
                        continue

                    closest_x = max(b["x"], min(ball["x"], b["x"] + b["w"]))
                    closest_y = max(b["y"], min(ball["y"], b["y"] + b["h"]))

                    dist_x = ball["x"] - closest_x
                    dist_y = ball["y"] - closest_y

                    if (dist_x * dist_x + dist_y * dist_y) < (r * r):
                        b["alive"] = False
                        if last_hitter in SCORES:
                            SCORES[last_hitter] += 100

                        overlap_left = (ball["x"] + r) - b["x"]
                        overlap_right = (b["x"] + b["w"]) - (ball["x"] - r)
                        overlap_top = (ball["y"] + r) - b["y"]
                        overlap_bottom = (b["y"] + b["h"]) - (ball["y"] - r)

                        if min(overlap_left, overlap_right) < min(overlap_top, overlap_bottom):
                            ball["vx"] = -ball["vx"]
                            step_vx = -step_vx
                            ball["x"] = b["x"] - r - 0.5 if overlap_left < overlap_right else b["x"] + b["w"] + r + 0.5
                        else:
                            ball["vy"] = -ball["vy"]
                            step_vy = -step_vy
                            ball["y"] = b["y"] - r - 0.5 if overlap_top < overlap_bottom else b["y"] + b["h"] + r + 0.5
                        break

            # 스테이지 클리어
            if sum(1 for b in bricks if b["alive"]) == 0:
                current_stage = (current_stage % TOTAL_STAGES) + 1
                bricks = generate_stage(current_stage)
                reset_ball()

            bot_list = [role for role, ws in SLOTS.items() if ws is None]
            waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info.get("state") == "waiting"]

            payload = json.dumps({
                "type": "game_update",
                "ball": ball,
                "paddles": paddle_positions,
                "names": PLAYER_NAMES,
                "scores": SCORES,
                "bot_slots": bot_list,
                "stage": current_stage,
                "waiting_users": waiting_users,
                "bricks": [b["id"] for b in bricks if not b["alive"]]
            })
            for ws in list(CONNECTED_CLIENTS.keys()):
                try:
                    await ws.send(payload)
                except:
                    pass

        await asyncio.sleep(0.016)

async def handler(websocket):
    state = "waiting" if game_started else "lobby"
    CONNECTED_CLIENTS[websocket] = {"role": None, "name": f"게스트{random.randint(100, 999)}", "state": state}

    if game_started:
        await websocket.send(json.dumps({
            "type": "waiting_room_notice",
            "bricks": bricks,
            "stage": current_stage
        }))
    await broadcast_lobby()

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "set_name":
                    client_name = str(data.get("name", "익명")).strip()[:10]
                    if client_name:
                        CONNECTED_CLIENTS[websocket]["name"] = client_name
                        role = CONNECTED_CLIENTS[websocket]["role"]
                        if role:
                            PLAYER_NAMES[role] = client_name
                    await broadcast_lobby()

                elif msg_type == "select_role":
                    if game_started:
                        continue
                    role = data.get("role")
                    for r in ["bottom", "left", "right"]:
                        if SLOTS[r] == websocket:
                            SLOTS[r] = None
                            PLAYER_NAMES[r] = "BOT"
                    if role in SLOTS:
                        SLOTS[role] = websocket
                        PLAYER_NAMES[role] = CONNECTED_CLIENTS[websocket]["name"]
                        CONNECTED_CLIENTS[websocket]["role"] = role
                    await broadcast_lobby()

                elif msg_type == "start_game":
                    global game_started, current_stage, bricks, SCORES
                    current_stage = 1
                    SCORES = {"bottom": 0, "left": 0, "right": 0}
                    bricks = generate_stage(current_stage)
                    reset_ball()
                    game_started = True
                    for ws in CONNECTED_CLIENTS:
                        CONNECTED_CLIENTS[ws]["state"] = "playing" if CONNECTED_CLIENTS[ws]["role"] else "waiting"

                    init_payload = json.dumps({
                        "type": "game_start",
                        "stage": current_stage,
                        "bricks": bricks
                    })
                    for ws in list(CONNECTED_CLIENTS.keys()):
                        try:
                            await ws.send(init_payload)
                        except:
                            pass
                    await broadcast_lobby()

                elif msg_type == "move":
                    role = CONNECTED_CLIENTS[websocket]["role"]
                    if role and game_started:
                        max_limit = WIDTH - 35 if role == "bottom" else HEIGHT - 35
                        paddle_positions[role] = max(35, min(max_limit, float(data["pos"])))

            except Exception as e:
                print(f"[메시지 파싱 안전 방어]: {e}")

    except websockets.ConnectionClosed:
        pass
    finally:
        for r in ["bottom", "left", "right"]:
            if SLOTS[r] == websocket:
                SLOTS[r] = None
                PLAYER_NAMES[r] = "BOT"
        CONNECTED_CLIENTS.pop(websocket, None)

        active_users = [ws for ws, info in CONNECTED_CLIENTS.items() if info.get("role")]
        if len(active_users) == 0:
            game_started = False
        await broadcast_lobby()

async def main():
    # Render $PORT 동적 포트와 로컬 8765 포트 호환
    port = int(os.environ.get("PORT", 8765))
    server = await websockets.serve(handler, "0.0.0.0", port)
    print(f"[{VERSION_TITLE}] 서버 가동 시작... 포트: {port}")
    await asyncio.gather(server.wait_closed(), game_loop())

if __name__ == "__main__":
    asyncio.run(main())
