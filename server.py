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

VERSION_TITLE = "정통알카노이드_블록피격수정_버전18"

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

ai_offsets = {
    "bottom": 0.0,
    "left": 0.0,
    "right": 0.0
}

magnet_active_until = {
    "bottom": 0.0,
    "left": 0.0,
    "right": 0.0
}

ball_stuck_to = None
ball_stuck_offset = 0.0
bot_release_timer = 0.0

BALL_SPEED_LEVEL = 6
BALL_BASE_SPEED = BALL_SPEED_LEVEL * 1.02

ball = {
    "x": WIDTH / 2,
    "y": HEIGHT / 2 + 100,
    "vx": 4.0,
    "vy": -4.0,
    "radius": 8
}

bricks = []

orb = {
    "angle": 0.0,
    "speed": 0.048,
    "radius": 13,
    "cx": 250,
    "cy": 250,
    "rail_r": 205,
    "holding_ball": False,
    "hold_rotated": 0.0
}

def generate_stage(stage_num):
    new_bricks = []
    brick_id = 0
    center_x, center_y = WIDTH / 2, HEIGHT / 2 - 10
    if stage_num == 1:
        rows, cols = 6, 6
        start_x = (WIDTH - (cols * 36)) / 2 + 3
        start_y = (HEIGHT - (rows * 22)) / 2 - 10
        for r in range(rows):
            for c in range(cols):
                new_bricks.append({"id": brick_id, "x": start_x + c * 36, "y": start_y + r * 22, "w": 30, "h": 14, "alive": True, "hp": 1, "hardened": False})
                brick_id += 1
    elif stage_num == 2:
        for r in range(7):
            for c in range(7):
                if r == 3 or c == 3 or (abs(r - 3) + abs(c - 3) <= 2):
                    new_bricks.append({"id": brick_id, "x": center_x - 126 + c * 36, "y": center_y - 77 + r * 22, "w": 30, "h": 14, "alive": True, "hp": 1, "hardened": False})
                    brick_id += 1
    else:
        for r in range(8):
            for c in range(8):
                if r in [0, 7] or c in [0, 7] or (r in [3, 4] and c in [3, 4]):
                    new_bricks.append({"id": brick_id, "x": center_x - 144 + c * 36, "y": center_y - 88 + r * 22, "w": 30, "h": 14, "alive": True, "hp": 1, "hardened": False})
                    brick_id += 1
    return new_bricks

def restore_broken_bricks():
    """깨진 블록 중 20%를 HP 2짜리 부활 블록으로 복원"""
    dead_bricks = [b for b in bricks if not b["alive"]]
    if not dead_bricks:
        return 0

    count_to_restore = max(1, round(len(dead_bricks) * 0.2))
    to_revive = random.sample(dead_bricks, min(count_to_restore, len(dead_bricks)))
    for b in to_revive:
        b["alive"] = True
        b["hp"] = 2
        b["hardened"] = True
    return len(to_revive)

def reset_ball():
    global ball, last_hitter, ai_offsets, orb, ball_stuck_to
    ball["x"] = WIDTH / 2
    ball["y"] = HEIGHT / 2 + 80
    angle = random.choice([-1, 1]) * random.uniform(0.35, 0.75)
    ball["vx"] = BALL_BASE_SPEED * math.sin(angle)
    ball["vy"] = -abs(BALL_BASE_SPEED * math.cos(angle))
    last_hitter = None
    ball_stuck_to = None
    orb["holding_ball"] = False
    orb["hold_rotated"] = 0.0
    ai_offsets = {r: random.uniform(-24, 24) for r in ai_offsets}

def release_stuck_ball(role):
    global ball_stuck_to, ball
    if ball_stuck_to != role:
        return

    offset = max(-1.0, min(1.0, ball_stuck_offset / 35.0))
    rebound_angle = offset * (math.pi / 3.0)

    if role == "bottom":
        ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
        ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
    elif role == "left":
        ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
    elif role == "right":
        ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
        ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)

    ball_stuck_to = None

bricks = generate_stage(current_stage)

def update_ai():
    ai_speed = BALL_BASE_SPEED * 0.92
    if SLOTS["bottom"] is None:
        target_x = ball["x"] + ai_offsets["bottom"]
        cx = paddle_positions["bottom"]
        paddle_positions["bottom"] += max(-ai_speed, min(ai_speed, target_x - cx))
        paddle_positions["bottom"] = max(40, min(WIDTH - 40, paddle_positions["bottom"]))

    if SLOTS["left"] is None:
        target_y = ball["y"] + ai_offsets["left"]
        cy = paddle_positions["left"]
        paddle_positions["left"] += max(-ai_speed, min(ai_speed, target_y - cy))
        paddle_positions["left"] = max(40, min(HEIGHT - 40, paddle_positions["left"]))

    if SLOTS["right"] is None:
        target_y = ball["y"] + ai_offsets["right"]
        cy = paddle_positions["right"]
        paddle_positions["right"] += max(-ai_speed, min(ai_speed, target_y - cy))
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
        "stage": current_stage,
        "speed_level": BALL_SPEED_LEVEL
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except Exception:
            pass

async def game_loop():
    global game_started, current_stage, bricks, ball, last_hitter, pause_until, orb, ai_offsets
    global ball_stuck_to, ball_stuck_offset, bot_release_timer
    P_LEN = 70

    while True:
        now = time.time()
        is_paused = (now < pause_until)
        sound_event = None

        if game_started:
            orb["angle"] = (orb["angle"] + orb["speed"]) % (2 * math.pi)
            orb_x = orb["cx"] + orb["rail_r"] * math.cos(orb["angle"])
            orb_y = orb["cy"] + orb["rail_r"] * math.sin(orb["angle"])

            charge_progress = 0.0
            if orb["holding_ball"]:
                orb["hold_rotated"] += orb["speed"]
                ball["x"] = orb_x
                ball["y"] = orb_y
                charge_progress = min(1.0, orb["hold_rotated"] / (2 * math.pi))

                if orb["hold_rotated"] >= (2 * math.pi):
                    orb["holding_ball"] = False
                    orb["hold_rotated"] = 0.0
                    center_dir = math.atan2(orb["cy"] - orb_y, orb["cx"] - orb_x)
                    toss_angle = center_dir + random.uniform(-math.pi / 4, math.pi / 4)

                    ball["vx"] = BALL_BASE_SPEED * 1.15 * math.cos(toss_angle)
                    ball["vy"] = BALL_BASE_SPEED * 1.15 * math.sin(toss_angle)
                    
                    push_dist = ball["radius"] + orb["radius"] + 4.0
                    ball["x"] = orb_x + push_dist * math.cos(center_dir)
                    ball["y"] = orb_y + push_dist * math.sin(center_dir)

                    sound_event = "orb"
                    charge_progress = 1.0
                    ai_offsets = {r: random.uniform(-24, 24) for r in ai_offsets}

            elif ball_stuck_to:
                if ball_stuck_to == "bottom":
                    ball["x"] = paddle_positions["bottom"] + ball_stuck_offset
                    ball["y"] = HEIGHT - 22 - ball["radius"]
                elif ball_stuck_to == "left":
                    ball["x"] = 22 + ball["radius"]
                    ball["y"] = paddle_positions["left"] + ball_stuck_offset
                elif ball_stuck_to == "right":
                    ball["x"] = WIDTH - 22 - ball["radius"]
                    ball["y"] = paddle_positions["right"] + ball_stuck_offset

                if SLOTS[ball_stuck_to] is None and now >= bot_release_timer:
                    release_stuck_ball(ball_stuck_to)
                    sound_event = "paddle"

            elif not is_paused:
                update_ai()

                sub_steps = 4
                step_vx = ball["vx"] / sub_steps
                step_vy = ball["vy"] / sub_steps

                for _ in range(sub_steps):
                    ball["x"] += step_vx
                    ball["y"] += step_vy

                    # 구슬 접촉 -> 20% 복원
                    d_orb = math.hypot(ball["x"] - orb_x, ball["y"] - orb_y)
                    if d_orb <= (ball["radius"] + orb["radius"]):
                        orb["holding_ball"] = True
                        orb["hold_rotated"] = 0.0
                        ball["x"] = orb_x
                        ball["y"] = orb_y
                        
                        revived_count = restore_broken_bricks()
                        sound_event = "restore" if revived_count > 0 else "catch"
                        break

                    # 1. 상단 벽
                    if ball["y"] - ball["radius"] <= 10:
                        ball["y"] = 10 + ball["radius"]
                        ball["vy"] = abs(ball["vy"])
                        step_vy = ball["vy"] / sub_steps
                        sound_event = "wall"

                    # 2. 하단 패들
                    if ball["y"] + ball["radius"] >= HEIGHT - 22:
                        pad_x = paddle_positions["bottom"]
                        if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                            last_hitter = "bottom"
                            offset = ball["x"] - pad_x

                            if now < magnet_active_until["bottom"]:
                                ball_stuck_to = "bottom"
                                ball_stuck_offset = offset
                                bot_release_timer = now + 1.0
                                sound_event = "catch"
                                break
                            else:
                                ball["y"] = HEIGHT - 22 - ball["radius"]
                                rebound_angle = (offset / (P_LEN / 2)) * (math.pi / 3.0)
                                ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                                ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                                step_vx = ball["vx"] / sub_steps
                                step_vy = ball["vy"] / sub_steps
                                sound_event = "paddle"
                                ai_offsets["bottom"] = random.uniform(-24, 24)
                        elif ball["y"] > HEIGHT + 30:
                            SCORES["bottom"] = max(0, SCORES["bottom"] - 200)
                            sound_event = "lose"
                            reset_ball()
                            break

                    # 3. 좌측 패들
                    if ball["x"] - ball["radius"] <= 22:
                        pad_y = paddle_positions["left"]
                        if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                            last_hitter = "left"
                            offset = ball["y"] - pad_y

                            if now < magnet_active_until["left"]:
                                ball_stuck_to = "left"
                                ball_stuck_offset = offset
                                bot_release_timer = now + 1.0
                                sound_event = "catch"
                                break
                            else:
                                ball["x"] = 22 + ball["radius"]
                                rebound_angle = (offset / (P_LEN / 2)) * (math.pi / 3.0)
                                ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
                                ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                                step_vx = ball["vx"] / sub_steps
                                step_vy = ball["vy"] / sub_steps
                                sound_event = "paddle"
                                ai_offsets["left"] = random.uniform(-24, 24)
                        elif ball["x"] < -30:
                            SCORES["left"] = max(0, SCORES["left"] - 200)
                            sound_event = "lose"
                            reset_ball()
                            break

                    # 4. 우측 패들
                    if ball["x"] + ball["radius"] >= WIDTH - 22:
                        pad_y = paddle_positions["right"]
                        if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                            last_hitter = "right"
                            offset = ball["y"] - pad_y

                            if now < magnet_active_until["right"]:
                                ball_stuck_to = "right"
                                ball_stuck_offset = offset
                                bot_release_timer = now + 1.0
                                sound_event = "catch"
                                break
                            else:
                                ball["x"] = WIDTH - 22 - ball["radius"]
                                rebound_angle = (offset / (P_LEN / 2)) * (math.pi / 3.0)
                                ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
                                ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
                                step_vx = ball["vx"] / sub_steps
                                step_vy = ball["vy"] / sub_steps
                                sound_event = "paddle"
                                ai_offsets["right"] = random.uniform(-24, 24)
                        elif ball["x"] > WIDTH + 30:
                            SCORES["right"] = max(0, SCORES["right"] - 200)
                            sound_event = "lose"
                            reset_ball()
                            break

                    # 5. 벽돌 충돌 및 HP 감량 판정
                    r = ball["radius"]
                    for b in bricks:
                        if not b["alive"]:
                            continue

                        closest_x = max(b["x"], min(ball["x"], b["x"] + b["w"]))
                        closest_y = max(b["y"], min(ball["y"], b["y"] + b["h"]))

                        dist_x = ball["x"] - closest_x
                        dist_y = ball["y"] - closest_y

                        if (dist_x * dist_x + dist_y * dist_y) < (r * r):
                            # [핵심] HP 1 감소
                            b["hp"] -= 1

                            if b["hp"] <= 0:
                                b["alive"] = False
                                sound_event = "brick"
                                if last_hitter in SCORES:
                                    SCORES[last_hitter] += 100

                                # 부활 블록을 완전히 파괴한 플레이어에게 15초 특수기능 부여
                                if b["hardened"] and last_hitter:
                                    magnet_active_until[last_hitter] = now + 15.0
                                    sound_event = "powerup"
                            else:
                                # 부활 블록 1회 타격 (HP 1 남음)
                                sound_event = "hard_hit"

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

                if sum(1 for b in bricks if b["alive"]) == 0:
                    current_stage = (current_stage % TOTAL_STAGES) + 1
                    bricks = generate_stage(current_stage)
                    reset_ball()
                    pause_until = time.time() + 2.0

            bot_list = [role for role, ws in SLOTS.items() if ws is None]
            waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info.get("state") == "waiting"]
            remaining_pause = max(0.0, pause_until - now)

            # 살아있는 벽돌 목록 완전 전송
            alive_bricks_list = [{
                "id": b["id"],
                "x": b["x"],
                "y": b["y"],
                "w": b["w"],
                "h": b["h"],
                "hp": b["hp"],
                "hardened": b["hardened"]
            } for b in bricks if b["alive"]]

            magnet_remain = {r: max(0.0, magnet_active_until[r] - now) for r in magnet_active_until}

            payload = json.dumps({
                "type": "game_update",
                "ball": ball,
                "paddles": paddle_positions,
                "names": PLAYER_NAMES,
                "scores": SCORES,
                "bot_slots": bot_list,
                "stage": current_stage,
                "waiting_users": waiting_users,
                "active_bricks": alive_bricks_list,
                "pause_sec": remaining_pause,
                "sound": sound_event,
                "magnet_remain": magnet_remain,
                "ball_stuck_to": ball_stuck_to,
                "orb": {
                    "x": orb_x,
                    "y": orb_y,
                    "rail_cx": orb["cx"],
                    "rail_cy": orb["cy"],
                    "rail_r": orb["rail_r"],
                    "holding": orb["holding_ball"],
                    "progress": charge_progress
                }
            })
            for ws in list(CONNECTED_CLIENTS.keys()):
                try:
                    await ws.send(payload)
                except Exception:
                    pass

        await asyncio.sleep(0.016)

async def handler(websocket):
    global game_started, current_stage, bricks, SCORES, pause_until, BALL_SPEED_LEVEL, BALL_BASE_SPEED

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
                "assigned_role": assigned_role
            }))
        else:
            CONNECTED_CLIENTS[websocket] = {"role": None, "name": new_user_name, "state": "waiting"}
            await websocket.send(json.dumps({
                "type": "waiting_room_notice",
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

                elif msg_type == "set_speed":
                    if not game_started:
                        lvl = max(1, min(10, int(data.get("level", 6))))
                        BALL_SPEED_LEVEL = lvl
                        BALL_BASE_SPEED = BALL_SPEED_LEVEL * 1.02
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
                    BALL_BASE_SPEED = BALL_SPEED_LEVEL * 1.02
                    reset_ball()
                    game_started = True
                    pause_until = time.time() + 2.0
                    
                    for ws in CONNECTED_CLIENTS:
                        CONNECTED_CLIENTS[ws]["state"] = "playing" if CONNECTED_CLIENTS[ws]["role"] else "waiting"

                    init_payload = json.dumps({
                        "type": "game_start",
                        "stage": current_stage
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

                elif msg_type == "release_ball":
                    role = CONNECTED_CLIENTS[websocket]["role"]
                    if role and ball_stuck_to == role:
                        release_stuck_ball(role)

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
