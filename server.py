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

VERSION_TITLE = "정통알카노이드_3종특수기능_버전20 (Catch, Multi, IronBall)"

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

# [특수 기능 버프 상태]
# type: None | "CATCH" | "MULTI" | "IRON"
player_powerups = {
    "bottom": {"type": None, "until": 0.0},
    "left": {"type": None, "until": 0.0},
    "right": {"type": None, "until": 0.0}
}

ball_stuck_to = None
ball_stuck_offset = 0.0
bot_release_timer = 0.0

BALL_SPEED_LEVEL = 6
BALL_BASE_SPEED = BALL_SPEED_LEVEL * 1.02

ORB_SPEED_LEVEL = 7
ORB_BASE_SPEED = (ORB_SPEED_LEVEL / 7.0) * 0.048

# 공 리스트 (멀티볼 지원)
# ball 객체: { id, x, y, vx, vy, radius, is_iron }
balls = []
ball_id_seq = 1

bricks = []

orb = {
    "angle": 0.0,
    "speed": ORB_BASE_SPEED,
    "radius": 9,
    "cx": 250,
    "cy": 250,
    "rail_r": 205,
    "holding_ball": False,
    "hold_rotated": 0.0
}

def create_ball(x, y, vx, vy, is_iron=False):
    global ball_id_seq
    b = {
        "id": ball_id_seq,
        "x": x,
        "y": y,
        "vx": vx,
        "vy": vy,
        "radius": 8,
        "is_iron": is_iron
    }
    ball_id_seq += 1
    return b

def reset_all_balls():
    global balls, last_hitter, ai_offsets, orb, ball_stuck_to
    balls.clear()
    angle = random.choice([-1, 1]) * random.uniform(0.35, 0.75)
    vx = BALL_BASE_SPEED * math.sin(angle)
    vy = -abs(BALL_BASE_SPEED * math.cos(angle))
    balls.append(create_ball(WIDTH / 2, HEIGHT / 2 + 80, vx, vy, False))

    last_hitter = None
    ball_stuck_to = None
    orb["holding_ball"] = False
    orb["hold_rotated"] = 0.0
    ai_offsets = {r: random.uniform(-24, 24) for r in ai_offsets}

def spawn_multiballs(source_ball):
    """멀티볼 발동: 기존 공을 기준으로 2개의 공 추가 생성 (총 3개)"""
    global balls
    base_angle = math.atan2(source_ball["vy"], source_ball["vx"])
    spd = BALL_BASE_SPEED

    # 각도 ±30도로 분기
    b1 = create_ball(source_ball["x"], source_ball["y"], spd * math.cos(base_angle - 0.5), spd * math.sin(base_angle - 0.5), source_ball.get("is_iron", False))
    b2 = create_ball(source_ball["x"], source_ball["y"], spd * math.cos(base_angle + 0.5), spd * math.sin(base_angle + 0.5), source_ball.get("is_iron", False))
    balls.extend([b1, b2])

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

def release_stuck_ball(role):
    global ball_stuck_to, balls
    if ball_stuck_to != role or not balls:
        return

    main_ball = balls[0]
    offset = max(-1.0, min(1.0, ball_stuck_offset / 35.0))
    rebound_angle = offset * (math.pi / 3.0)

    if role == "bottom":
        main_ball["vx"] = BALL_BASE_SPEED * math.sin(rebound_angle)
        main_ball["vy"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
    elif role == "left":
        main_ball["vx"] = BALL_BASE_SPEED * math.cos(rebound_angle)
        main_ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)
    elif role == "right":
        main_ball["vx"] = -BALL_BASE_SPEED * math.cos(rebound_angle)
        main_ball["vy"] = BALL_BASE_SPEED * math.sin(rebound_angle)

    ball_stuck_to = None

bricks = generate_stage(current_stage)
reset_all_balls()

def update_ai():
    if not balls:
        return
    lead_ball = balls[0]
    ai_speed = BALL_BASE_SPEED * 0.92

    if SLOTS["bottom"] is None:
        target_x = lead_ball["x"] + ai_offsets["bottom"]
        cx = paddle_positions["bottom"]
        paddle_positions["bottom"] += max(-ai_speed, min(ai_speed, target_x - cx))
        paddle_positions["bottom"] = max(40, min(WIDTH - 40, paddle_positions["bottom"]))

    if SLOTS["left"] is None:
        target_y = lead_ball["y"] + ai_offsets["left"]
        cy = paddle_positions["left"]
        paddle_positions["left"] += max(-ai_speed, min(ai_speed, target_y - cy))
        paddle_positions["left"] = max(40, min(HEIGHT - 40, paddle_positions["left"]))

    if SLOTS["right"] is None:
        target_y = lead_ball["y"] + ai_offsets["right"]
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
        "speed_level": BALL_SPEED_LEVEL,
        "orb_speed_level": ORB_SPEED_LEVEL
    })
    for ws in list(CONNECTED_CLIENTS.keys()):
        try:
            await ws.send(payload)
        except Exception:
            pass

async def game_loop():
    global game_started, current_stage, bricks, balls, last_hitter, pause_until, orb, ai_offsets
    global ball_stuck_to, ball_stuck_offset, bot_release_timer, player_powerups
    P_LEN = 70

    while True:
        now = time.time()
        is_paused = (now < pause_until)
        sound_event = None

        if game_started:
            # 특수 버프 만료 검사
            for r in ["bottom", "left", "right"]:
                if player_powerups[r]["type"] and now >= player_powerups[r]["until"]:
                    # 멀티볼 만료 시 공 1개로 복구
                    if player_powerups[r]["type"] == "MULTI" and len(balls) > 1:
                        balls = [balls[0]]
                    # 무쇠공 만료 시 일반공 복구
                    if player_powerups[r]["type"] == "IRON":
                        for b in balls:
                            b["is_iron"] = False
                    player_powerups[r]["type"] = None

            orb["angle"] = (orb["angle"] + orb["speed"]) % (2 * math.pi)
            orb_x = orb["cx"] + orb["rail_r"] * math.cos(orb["angle"])
            orb_y = orb["cy"] + orb["rail_r"] * math.sin(orb["angle"])

            charge_progress = 0.0

            # 1. 마법구슬 공 포획 상태 처리
            if orb["holding_ball"]:
                orb["hold_rotated"] += orb["speed"]
                if balls:
                    balls[0]["x"] = orb_x
                    balls[0]["y"] = orb_y
                charge_progress = min(1.0, orb["hold_rotated"] / (2 * math.pi))

                if orb["hold_rotated"] >= (2 * math.pi):
                    orb["holding_ball"] = False
                    orb["hold_rotated"] = 0.0
                    center_dir = math.atan2(orb["cy"] - orb_y, orb["cx"] - orb_x)
                    toss_angle = center_dir + random.uniform(-math.pi / 4, math.pi / 4)

                    if balls:
                        balls[0]["vx"] = BALL_BASE_SPEED * 1.15 * math.cos(toss_angle)
                        balls[0]["vy"] = BALL_BASE_SPEED * 1.15 * math.sin(toss_angle)
                        push_dist = balls[0]["radius"] + orb["radius"] + 4.0
                        balls[0]["x"] = orb_x + push_dist * math.cos(center_dir)
                        balls[0]["y"] = orb_y + push_dist * math.sin(center_dir)

                    sound_event = "orb"
                    charge_progress = 1.0
                    ai_offsets = {r: random.uniform(-24, 24) for r in ai_offsets}

            # 2. 패들에 공이 붙어있는 경우 (자석 기능)
            elif ball_stuck_to and balls:
                main_ball = balls[0]
                if ball_stuck_to == "bottom":
                    main_ball["x"] = paddle_positions["bottom"] + ball_stuck_offset
                    main_ball["y"] = HEIGHT - 22 - main_ball["radius"]
                elif ball_stuck_to == "left":
                    main_ball["x"] = 22 + main_ball["radius"]
                    main_ball["y"] = paddle_positions["left"] + ball_stuck_offset
                elif ball_stuck_to == "right":
                    main_ball["x"] = WIDTH - 22 - main_ball["radius"]
                    main_ball["y"] = paddle_positions["right"] + ball_stuck_offset

                if SLOTS[ball_stuck_to] is None and now >= bot_release_timer:
                    release_stuck_ball(ball_stuck_to)
                    sound_event = "paddle"

            elif not is_paused:
                update_ai()

                dead_balls = []

                for ball in balls:
                    sub_steps = 4
                    step_vx = ball["vx"] / sub_steps
                    step_vy = ball["vy"] / sub_steps

                    for _ in range(sub_steps):
                        ball["x"] += step_vx
                        ball["y"] += step_vy

                        # 마법구슬 판정 (30% 겹침)
                        overlap_threshold = (ball["radius"] + orb["radius"]) * 0.70
                        d_orb = math.hypot(ball["x"] - orb_x, ball["y"] - orb_y)
                        if d_orb <= overlap_threshold and not orb["holding_ball"]:
                            orb["holding_ball"] = True
                            orb["hold_rotated"] = 0.0
                            ball["x"] = orb_x
                            ball["y"] = orb_y
                            revived_count = restore_broken_bricks()
                            sound_event = "restore" if revived_count > 0 else "catch"
                            break

                        # 상단 벽 충돌
                        if ball["y"] - ball["radius"] <= 10:
                            ball["y"] = 10 + ball["radius"]
                            ball["vy"] = abs(ball["vy"])
                            step_vy = ball["vy"] / sub_steps
                            sound_event = "wall"

                        # 하단 패들
                        if ball["y"] + ball["radius"] >= HEIGHT - 22:
                            pad_x = paddle_positions["bottom"]
                            if pad_x - P_LEN / 2 <= ball["x"] <= pad_x + P_LEN / 2:
                                last_hitter = "bottom"
                                offset = ball["x"] - pad_x

                                # 1번 특수기능(CATCH) 활성화 중일 때
                                if player_powerups["bottom"]["type"] == "CATCH" and now < player_powerups["bottom"]["until"]:
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
                                dead_balls.append(ball)
                                break

                        # 좌측 패들
                        if ball["x"] - ball["radius"] <= 22:
                            pad_y = paddle_positions["left"]
                            if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                                last_hitter = "left"
                                offset = ball["y"] - pad_y

                                if player_powerups["left"]["type"] == "CATCH" and now < player_powerups["left"]["until"]:
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
                                dead_balls.append(ball)
                                break

                        # 우측 패들
                        if ball["x"] + ball["radius"] >= WIDTH - 22:
                            pad_y = paddle_positions["right"]
                            if pad_y - P_LEN / 2 <= ball["y"] <= pad_y + P_LEN / 2:
                                last_hitter = "right"
                                offset = ball["y"] - pad_y

                                if player_powerups["right"]["type"] == "CATCH" and now < player_powerups["right"]["until"]:
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
                                dead_balls.append(ball)
                                break

                        # 블록 충돌
                        r = ball["radius"]
                        is_iron = ball.get("is_iron", False)

                        for b in bricks:
                            if not b["alive"]:
                                continue

                            closest_x = max(b["x"], min(ball["x"], b["x"] + b["w"]))
                            closest_y = max(b["y"], min(ball["y"], b["y"] + b["h"]))

                            dist_x = ball["x"] - closest_x
                            dist_y = ball["y"] - closest_y

                            if (dist_x * dist_x + dist_y * dist_y) < (r * r):
                                # 3번 특수기능: 무쇠공은 스치기만 해도 원샷 관통 파괴!
                                if is_iron:
                                    b["hp"] = 0
                                    b["alive"] = False
                                    sound_event = "iron_hit"
                                    if last_hitter in SCORES:
                                        SCORES[last_hitter] += 100
                                else:
                                    # 일반 타격 판정
                                    b["hp"] -= 1
                                    if b["hp"] <= 0:
                                        b["alive"] = False
                                        sound_event = "brick"
                                        if last_hitter in SCORES:
                                            SCORES[last_hitter] += 100

                                        # 부활 블록 격파 시 3가지 특수 기능 중 1개 랜덤 지급 (15초)
                                        if b["hardened"] and last_hitter:
                                            chosen_skill = random.choice(["CATCH", "MULTI", "IRON"])
                                            player_powerups[last_hitter] = {
                                                "type": chosen_skill,
                                                "until": now + 15.0
                                            }
                                            sound_event = "powerup"

                                            if chosen_skill == "MULTI":
                                                spawn_multiballs(ball)
                                            elif chosen_skill == "IRON":
                                                for bl in balls:
                                                    bl["is_iron"] = True
                                    else:
                                        sound_event = "hard_hit"

                                    # 일반공은 충돌 반사 (무쇠공은 반사 없이 직진 관통)
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

                # 탈락한 공 정리
                for db in dead_balls:
                    if db in balls:
                        balls.remove(db)

                # 모든 공이 떨어진 경우 실점 및 리셋
                if len(balls) == 0:
                    sound_event = "lose"
                    reset_all_balls()

                # 모든 블록 클리어 -> 다음 스테이지
                if sum(1 for b in bricks if b["alive"]) == 0:
                    current_stage = (current_stage % TOTAL_STAGES) + 1
                    bricks = generate_stage(current_stage)
                    reset_all_balls()
                    pause_until = time.time() + 2.0

            bot_list = [role for role, ws in SLOTS.items() if ws is None]
            waiting_users = [info["name"] for ws, info in CONNECTED_CLIENTS.items() if info.get("state") == "waiting"]
            remaining_pause = max(0.0, pause_until - now)

            alive_bricks_list = [{
                "id": b["id"],
                "x": b["x"],
                "y": b["y"],
                "w": b["w"],
                "h": b["h"],
                "hp": b["hp"],
                "hardened": b["hardened"]
            } for b in bricks if b["alive"]]

            # 플레이어별 특수 기능 상태 정보
            powerup_status = {}
            for r in ["bottom", "left", "right"]:
                rem = max(0.0, player_powerups[r]["until"] - now)
                powerup_status[r] = {
                    "type": player_powerups[r]["type"] if rem > 0 else None,
                    "remain": rem
                }

            payload = json.dumps({
                "type": "game_update",
                "balls": balls,
                "paddles": paddle_positions,
                "names": PLAYER_NAMES,
                "scores": SCORES,
                "bot_slots": bot_list,
                "stage": current_stage,
                "waiting_users": waiting_users,
                "active_bricks": alive_bricks_list,
                "pause_sec": remaining_pause,
                "sound": sound_event,
                "powerup_status": powerup_status,
                "ball_stuck_to": ball_stuck_to,
                "orb": {
                    "x": orb_x,
                    "y": orb_y,
                    "rail_cx": orb["cx"],
                    "rail_cy": orb["cy"],
                    "rail_r": orb["rail_r"],
                    "radius": orb["radius"],
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
    global game_started, current_stage, bricks, SCORES, pause_until
    global BALL_SPEED_LEVEL, BALL_BASE_SPEED, ORB_SPEED_LEVEL, ORB_BASE_SPEED, orb

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

                elif msg_type == "set_orb_speed":
                    if not game_started:
                        lvl = max(1, min(10, int(data.get("level", 7))))
                        ORB_SPEED_LEVEL = lvl
                        ORB_BASE_SPEED = (ORB_SPEED_LEVEL / 7.0) * 0.048
                        orb["speed"] = ORB_BASE_SPEED
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
                    ORB_BASE_SPEED = (ORB_SPEED_LEVEL / 7.0) * 0.048
                    orb["speed"] = ORB_BASE_SPEED
                    reset_all_balls()
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
