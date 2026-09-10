import asyncio
import json
import math
import random
import websockets

WIDTH = 500
HEIGHT = 500

VERSION_TITLE = "정밀물리엔진버전7 (Precision Collision & Anti-Ghost)"

SLOTS = {"bottom": None, "left": None, "right": None}
PLAYER_NAMES = {"bottom": "BOT", "left": "BOT", "right": "BOT"}
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
    global ball
    ball["x"] = WIDTH / 2
    ball["y"] = HEIGHT / 2 + 80
    angle = random.uniform(-0.6, 0.6)
    ball["vx"] = BALL_BASE_SPEED * math.sin(angle)
    ball["vy"] = -abs(BALL_BASE_SPEED * math.cos(angle))

bricks = generate_stage(current_stage)

def update_ai():
    ai_speed = 6.0
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
        if ws is None:
            slots_info[role] = {"type": "BOT", "name": "BOT"}
        else:
            slots_info[role] = {"type": "USER", "name": PLAYER_NAMES[role]}

    waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info["state"] == "waiting"]

    payload = json.dumps({
        "type": "lobby_state",
        "title": VERSION_TITLE,
        "slots": slots_info,
        "game_started": game_started,
        "waiting_users": waiting_users,
        "stage": current_stage
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except:
            pass

def enforce_speed(vx, vy):
    current_speed = math.hypot(vx, vy)
    if current_speed == 0:
        return BALL_BASE_SPEED, -BALL_BASE_SPEED
    scale = BALL_BASE_SPEED / current_speed
    return vx * scale, vy * scale

async def game_loop():
    global game_started, current_stage, bricks, ball
    P_LEN = 70

    while True:
        if game_started:
            update_ai()

            # [핵심 개선] 터널링 방지를 위한 4회 서브스텝 (초정밀 물리 분할)
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
                    step_vy = abs(step_vy)

                # 2. 하단 패들 충돌 (곡면 반사 및 침투 방지)
                if ball["y"] + ball["radius"] >= HEIGHT - 22:
                    pad_x = paddle_positions["bottom"]
                    if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                        ball["y"] = HEIGHT - 22 - ball["radius"]  # 패들 위로 위치 강제 보정
                        offset = (ball["x"] - pad_x) / (P_LEN / 2)
                        rebound_angle = offset * (math.pi / 3)
                        ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                    elif ball["y"] > HEIGHT + 30:
                        reset_ball()
                        break

                # 3. 좌측 패들 충돌 (곡면 반사 및 침투 방지)
                if ball["x"] - ball["radius"] <= 22:
                    pad_y = paddle_positions["left"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["x"] = 22 + ball["radius"]  # 패들 우측으로 위치 강제 보정
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        adj_offset = max(-1.0, min(1.0, offset - 0.25))
                        rebound_angle = adj_offset * (math.pi / 3.2)
                        ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        if abs(ball["vy"]) < 2.5:
                            ball["vy"] = -2.8 if offset <= 0 else 2.8
                        ball["vx"], ball["vy"] = enforce_speed(ball["vx"], ball["vy"])
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                    elif ball["x"] < -30:
                        reset_ball()
                        break

                # 4. 우측 패들 충돌 (곡면 반사 및 침투 방지)
                if ball["x"] + ball["radius"] >= WIDTH - 22:
                    pad_y = paddle_positions["right"]
                    if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                        ball["x"] = WIDTH - 22 - ball["radius"]  # 패들 좌측으로 위치 강제 보정
                        offset = (ball["y"] - pad_y) / (P_LEN / 2)
                        adj_offset = max(-1.0, min(1.0, offset - 0.25))
                        rebound_angle = adj_offset * (math.pi / 3.2)
                        ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                        if abs(ball["vy"]) < 2.5:
                            ball["vy"] = -2.8 if offset <= 0 else 2.8
                        ball["vx"], ball["vy"] = enforce_speed(ball["vx"], ball["vy"])
                        step_vx = ball["vx"] / sub_steps
                        step_vy = ball["vy"] / sub_steps
                    elif ball["x"] > WIDTH + 30:
                        reset_ball()
                        break

                # 5. [핵심 개선] 정밀 Circle-AABB 최근접점 충돌 판정 (유령 반사 및 관통 완벽 차단)
                hit_brick = None
                r = ball["radius"]
                
                for b in bricks:
                    if not b["alive"]:
                        continue

                    # 사각형 내에서 공 중심과 가장 가까운 점(Closest Point) 계산
                    closest_x = max(b["x"], min(ball["x"], b["x"] + b["w"]))
                    closest_y = max(b["y"], min(ball["y"], b["y"] + b["h"]))

                    dist_x = ball["x"] - closest_x
                    dist_y = ball["y"] - closest_y
                    distance_sq = (dist_x * dist_x) + (dist_y * dist_y)

                    # 실제 원의 반지름 이내로 들어왔을 때만 진짜 충돌 인정 (유령 반사 방지)
                    if distance_sq < (r * r):
                        hit_brick = b
                        b["alive"] = False

                        # 충돌 깊이(침투량)에 따라 법선 방향 결정
                        overlap_left = (ball["x"] + r) - b["x"]
                        overlap_right = (b["x"] + b["w"]) - (ball["x"] - r)
                        overlap_top = (ball["y"] + r) - b["y"]
                        overlap_bottom = (b["y"] + b["h"]) - (ball["y"] - r)

                        min_overlap_x = min(overlap_left, overlap_right)
                        min_overlap_y = min(overlap_top, overlap_bottom)

                        if min_overlap_x < min_overlap_y:
                            # 좌우 측면 충돌
                            ball["vx"] = -ball["vx"]
                            step_vx = -step_vx
                            # 파묻힘 방지 밀어내기
                            if overlap_left < overlap_right:
                                ball["x"] = b["x"] - r - 0.5
                            else:
                                ball["x"] = b["x"] + b["w"] + r + 0.5
                        else:
                            # 상하 면 충돌
                            ball["vy"] = -ball["vy"]
                            step_vy = -step_vy
                            # 파묻힘 방지 밀어내기
                            if overlap_top < overlap_bottom:
                                ball["y"] = b["y"] - r - 0.5
                            else:
                                ball["y"] = b["y"] + b["h"] + r + 0.5
                        
                        # 1서브스텝 당 1개의 벽돌만 처리하고 즉시 루프 탈출 (이중 충돌 연산 왜곡 방지)
                        break

            # 스테이지 클리어 확인
            if sum(1 for b in bricks if b["alive"]) == 0:
                current_stage = (current_stage % TOTAL_STAGES) + 1
                bricks = generate_stage(current_stage)
                reset_ball()

            # 인게임 상태 브로드캐스트
            bot_list = [role for role, ws in SLOTS.items() if ws is None]
            waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info["state"] == "waiting"]
            
            payload = json.dumps({
                "type": "game_update",
                "ball": ball,
                "paddles": paddle_positions,
                "names": PLAYER_NAMES,
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
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "set_name":
                CONNECTED_CLIENTS[websocket]["name"] = str(data.get("name", "익명"))[:10]
                role = CONNECTED_CLIENTS[websocket]["role"]
                if role:
                    PLAYER_NAMES[role] = CONNECTED_CLIENTS[websocket]["name"]
                await broadcast_lobby()

            elif msg_type == "select_role":
                if game_started:
                    continue
                role = data.get("role")
                for r in ["bottom", "left", "right"]:
                    if SLOTS[r] == websocket:
                        SLOTS[r] = None
                        PLAYER_NAMES[r] = "BOT"
                if role in SLOTS and (SLOTS[role] is None or SLOTS[role] == websocket):
                    SLOTS[role] = websocket
                    PLAYER_NAMES[role] = CONNECTED_CLIENTS[websocket]["name"]
                    CONNECTED_CLIENTS[websocket]["role"] = role
                await broadcast_lobby()

            elif msg_type == "start_game":
                global game_started, current_stage, bricks
                current_stage = 1
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
                    await ws.send(init_payload)
                await broadcast_lobby()

            elif msg_type == "move":
                role = CONNECTED_CLIENTS[websocket]["role"]
                if role and game_started:
                    max_limit = WIDTH - 35 if role == "bottom" else HEIGHT - 35
                    paddle_positions[role] = max(35, min(max_limit, data["pos"]))

    except websockets.ConnectionClosed:
        pass
    finally:
        for r in ["bottom", "left", "right"]:
            if SLOTS[r] == websocket:
                SLOTS[r] = None
                PLAYER_NAMES[r] = "BOT"
        CONNECTED_CLIENTS.pop(websocket, None)
        
        active_users = [ws for ws, info in CONNECTED_CLIENTS.items() if info["role"]]
        if len(active_users) == 0:
            game_started = False
        await broadcast_lobby()

async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    print(f"[{VERSION_TITLE}] 서버 정상 가동...")
    await asyncio.gather(server.wait_closed(), game_loop())

if __name__ == "__main__":
    asyncio.run(main())
