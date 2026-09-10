import asyncio
import http
import json
import math
import os
import random
import time
import websockets

WIDTH = 500
HEIGHT = 500

VERSION_TITLE = "무수직반사_스코어버전10 (Magic Orb Rail)"

SLOTS = {"bottom": None, "left": None, "right": None}
PLAYER_NAMES = {"bottom": "BOT", "left": "BOT", "right": "BOT"}
SCORES = {"bottom": 0, "left": 0, "right": 0}
CONNECTED_CLIENTS = {}

game_started = False
pause_until = 0.0
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

# [마법구슬 및 원형 레일 상태 변수]
orb = {
    "angle": 0.0,
    "speed": 0.045,      # 회전 속도 (rad/frame)
    "radius": 11,        # 마법구슬 크기
    "cx": 250,
    "cy": 230,
    "rail_r": 135
}

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

def update_rail_geometry():
    """남은 블록들의 분포에 맞추어 원형 레일의 중심과 반지름을 동적으로 연동"""
    global orb
    alive_bricks = [b for b in bricks if b["alive"]]
    if not alive_bricks:
        return

    min_x = min(b["x"] for b in alive_bricks)
    max_x = max(b["x"] + b["w"] for b in alive_bricks)
    min_y = min(b["y"] for b in alive_bricks)
    max_y = max(b["y"] + b["h"] for b in alive_bricks)

    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    # 중심에서 가장 먼 코너까지의 거리 + 여유 마진 18px
    max_dist = 0
    for b in alive_bricks:
        for px in [b["x"], b["x"] + b["w"]]:
            for py in [b["y"], b["y"] + b["h"]]:
                d = math.hypot(px - cx, py - cy)
                if d > max_dist:
                    max_dist = d

    orb["cx"] = cx
    orb["cy"] = cy
    orb["rail_r"] = max(45, max_dist + 18)

bricks = generate_stage(current_stage)
update_rail_geometry()

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
        except Exception:
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
    global game_started, current_stage, bricks, ball, last_hitter, pause_until, orb
    P_LEN = 70

    while True:
        now = time.time()
        is_paused = (now < pause_until)

        if game_started:
            # 1. 마법구슬 레일 위 궤도 회전
            orb["angle"] = (orb["angle"] + orb["speed"]) % (2 * math.pi)
            orb_x = orb["cx"] + orb["rail_r"] * math.cos(orb["angle"])
            orb_y = orb["cy"] + orb["rail_r"] * math.sin(orb["angle"])

            if not is_paused:
                update_ai()

                sub_steps = 4
                step_vx = ball["vx"] / sub_steps
                step_vy = ball["vy"] / sub_steps

                for _ in range(sub_steps):
                    ball["x"] += step_vx
                    ball["y"] += step_vy

                    # [핵심] 마법구슬과 공의 충돌 및 레일 내부 랜덤 토스 판정
                    d_orb = math.hypot(ball["x"] - orb_x, ball["y"] - orb_y)
                    if d_orb <= (ball["radius"] + orb["radius"]):
                        # 구슬 위치에서 서클 중심을 향하는 기본 각도 계산
                        center_dir = math.atan2(orb["cy"] - orb_y, orb["cx"] - orb_x)
                        # 내부 방향으로 ±45도(π/4) 범위 내 랜덤 반사각 생성
                        toss_angle = center_dir + random.uniform(-math.pi / 4, math.pi / 4)
                        
                        ball["vx"] = BALL_BASE_SPEED * 1.15 * math.cos(toss_angle)
                        ball["vy"] = BALL_BASE_SPEED * 1.15 * math.sin(toss_angle)
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "y")
                        
                        # 구슬 밖으로 공 밀어내기
                        push_dist = ball["radius"] + orb["radius"] + 2.0
                        ball["x"] = orb_x + push_dist * math.cos(toss_angle)
                        ball["y"] = orb_y + push_dist * math.sin(toss_angle)

                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                        break

                    # 2. 천장
                    if ball["y"] - ball["radius"] <= 10:
                        ball["y"] = 10 + ball["radius"]
                        ball["vy"] = abs(ball["vy"])
                        ball["vx"], ball["vy"] = enforce_non_vertical(ball["vx"], ball["vy"], "y")
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps

                    # 3. 하단 패들
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

                    # 4. 좌측 패들
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

                    # 5. 우측 패들
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

                    # 6. 벽돌 충돌
                    r = ball["radius"]
                    hit_brick = False
                    for b in bricks:
                        if not b["alive"]:
                            continue

                        closest_x = max(b["x"], min(ball["x"], b["x"] + b["w"]))
                        closest_y = max(b["y"], min(ball["y"], b["y"] + b["h"]))

                        dist_x = ball["x"] - closest_x
                        dist_y = ball["y"] - closest_y

                        if (dist_x * dist_x + dist_y * dist_y) < (r * r):
                            b["alive"] = False
                            hit_brick = True
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

                    if hit_brick:
                        update_rail_geometry()

                if sum(1 for b in bricks if b["alive"]) == 0:
                    current_stage = (current_stage % TOTAL_STAGES) + 1
                    bricks = generate_stage(current_stage)
                    reset_ball()
                    update_rail_geometry()
                    pause_until = time.time() + 2.0

            bot_list = [role for role, ws in SLOTS.items() if ws is None]
            waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info.get("state") == "waiting"]
            remaining_pause = max(0.0, pause_until - now)

            payload = json.dumps({
                "type": "game_update",
                "ball": ball,
                "paddles": paddle_positions,
                "names": PLAYER_NAMES,
                "scores": SCORES,
                "bot_slots": bot_list,
                "stage": current_stage,
                "waiting_users": waiting_users,
                "bricks": [b["id"] for b in bricks if not b["alive"]],
                "pause_sec": remaining_pause,
                "orb": {
                    "x": orb["cx"] + orb["rail_r"] * math.cos(orb["angle"]),
                    "y": orb["cy"] + orb["rail_r"] * math.sin(orb["angle"]),
                    "rail_cx": orb["cx"],
                    "rail_cy": orb["cy"],
                    "rail_r": orb["rail_r"]
                }
            })
            for ws in list(CONNECTED_CLIENTS.keys()):
                try:
                    await ws.send(payload)
                except Exception:
                    pass

        await asyncio.sleep(0.016)

async def handler(websocket):
    global game_started, current_stage, bricks, SCORES, pause_until

    new_user_name = f"플레이어{random.randint(100, 999)}"
    assigned_role = None

    if game_started:
        empty_slots = [r for r in ["bottom", "left", "right"] if SLOTS[r] is None]
        if empty_slots:
            assigned_role = empty_slots[0]
            SLOTS[assigned_role] = websocket
            PLAYER_NAMES[assigned_role] = new_user_name
            CONNECTED_CLIENTS[websocket] = {"role": assigned_role, "name": new_user_name, "state": "playing"}
            pause_until = time.time() + 2.0

            await websocket.send(json.dumps({
                "type": "game_start",
                "stage": current_stage,
                "bricks": bricks,
                "assigned_role": assigned_role
            }))
        else:
            CONNECTED_CLIENTS[websocket] = {"role": None, "name": new_user_name, "state": "waiting"}
            await websocket.send(json.dumps({
                "type": "waiting_room_notice",
                "bricks": bricks,
                "stage": current_stage
            }))
    else:
        CONNECTED_CLIENTS[websocket] = {"role": None, "name": new_user_name, "state": "lobby"}

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
                    current_stage = 1
                    SCORES = {"bottom": 0, "left": 0, "right": 0}
                    bricks = generate_stage(current_stage)
                    update_rail_geometry()
                    reset_ball()
                    game_started = True
                    pause_until = time.time() + 2.0
                    
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
                        except Exception:
                            pass
                    await broadcast_lobby()

                elif msg_type == "move":
                    role = CONNECTED_CLIENTS[websocket]["role"]
                    if role and game_started:
                        max_limit = WIDTH - 35 if role == "bottom" else HEIGHT - 35
                        paddle_positions[role] = max(35, min(max_limit, float(data["pos"])))

            except Exception as parse_err:
                print(f"[메시지 파싱 방어]: {parse_err}")

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

async def health_check_handler(path, request_headers):
    if request_headers.get("Upgrade", "").lower() != "websocket":
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"Server Live OK\n"
    return None

async def main():
    port = int(os.environ.get("PORT", 8765))
    server = await websockets.serve(
        handler,
        "0.0.0.0",
        port,
        process_request=health_check_handler
    )
    print(f"[{VERSION_TITLE}] 가동... 포트: {port}")
    await asyncio.gather(server.wait_closed(), game_loop())

if __name__ == "__main__":
    asyncio.run(main())
