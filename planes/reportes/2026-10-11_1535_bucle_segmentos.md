# Bucle de segmentos de video — src/core/capcut_project.py

## 1. Bucle de segmentos completo (líneas 1310-1444)

1310:         for it in items:
1311:             self._check_cancelled()
1312:             if it.image_path is None:
1313:                 log.warning("Escena %d sin imagen; se omite material.", it.order)
1314:                 continue
1315:             start_us = it.start_us if it.duration_us > 0 else prev_end
1316:             duration_us = it.duration_us if it.duration_us > 0 else 1_000_000
1317:             prev_end = start_us + duration_us
1318:             abs_path = it.image_path.resolve().as_posix()
1319:             is_video = it.image_path.suffix.lower() in config.VIDEO_EXTENSIONS
1320:             if is_video:
1321:                 width, height = 1920, 1080
1322:                 try:
1323:                     import subprocess
1324:                     result = subprocess.run(
1325:                         ["ffprobe", "-v", "error",
1326:                          "-show_entries", "format=duration",
1327:                          "-of", "default=noprint_wrappers=1:nokey=1",
1328:                          str(it.image_path)],
1329:                         capture_output=True, text=True, timeout=10,
1330:                     )
1331:                     if result.returncode == 0 and result.stdout.strip():
1332:                         vid_dur_s = float(result.stdout.strip())
1333:                         vid_dur_us = int(round(vid_dur_s * 1_000_000))
1334:                         if vid_dur_us < duration_us:
1335:                             speed = round(vid_dur_us / duration_us, 4)
1336:                             log.info(
1337:                                 "Escena %d · video %s: dur=%d us < frase=%d us → speed=%.4f",
1338:                                 it.order, it.image_path.name, vid_dur_us, duration_us, speed,
1339:                             )
1340:                         else:
1341:                             speed = 1.0
1342:                     else:
1343:                         speed = 1.0
1344:                 except Exception:
1345:                     speed = 1.0
1346:                 cover_scale = 1.0
1347:                 zoom_mult = 1.0
1348:                 zoom_base = 1.0
1349:                 position_points = None
1350:                 refs: list[str] = []
1351:                 enable_hsl = False
1352:                 enable_adjust = False
1353:                 mat = self._build_photo_material(
1354:                     content, abs_path, width, height, duration_us, it.image_path.stem)
1355:                 mat["type"] = "video"
1356:                 photo_materials.append(mat)
1357:                 seg = copy.deepcopy(canonical.VIDEO_TRACK["segments"][0])
1358:                 seg["id"] = new_id()
1359:                 seg["material_id"] = mat["id"]
1360:                 seg["render_index"] = 0
1361:                 seg["track_render_index"] = 0
1362:                 seg["source_timerange"] = {"start": 0, "duration": duration_us}
1363:                 seg["target_timerange"] = {"start": start_us, "duration": duration_us}
1364:                 seg["speed"] = speed
1365:                 seg["clip"]["scale"] = {"x": cover_scale, "y": cover_scale}
1366:                 seg["uniform_scale"] = {"on": True, "value": 1.0}
1367:                 seg["common_keyframes"] = []
1368:                 seg["enable_hsl"] = False
1369:                 seg["enable_adjust"] = False
1370:                 seg["extra_material_refs"] = []
1371:                 video_segments.append(seg)
1372:             else:
1373:                 width, height = _image_size(it.image_path)
1374:                 cover_scale = _cover_scale(canvas_w, canvas_h, width, height)
1375:                 zoom_min = edit_profile.zoom_end_min
1376:                 zoom_max = edit_profile.zoom_end_max
1377:                 zoom_mult = random.uniform(zoom_min, zoom_max)
1378:                 action = _has_action_keyword(it.scene_text) or _has_action_keyword(it.segment_text)
1379:                 pan_ratio = getattr(edit_profile, 'pan_ratio', PAN_RATIO)
1380:                 pan_amp = getattr(edit_profile, 'pan_amplitude', PAN_AMPLITUDE)
1381:                 shake_ratio = getattr(edit_profile, 'shake_ratio', 1.0)
1382:                 shake_amp = getattr(edit_profile, 'shake_amplitude', SHAKE_AMPLITUDE)
1383:                 shake_boost = getattr(edit_profile, 'shake_zoom_boost', SHAKE_ZOOM_BOOST)
1384:                 pan_dx = pan_dy = 0.0
1385:                 if edit_profile.enable_camera_shake and action:
1386:                     if random.random() < pan_ratio:
1387:                         amp = random.uniform(*pan_amp)
1388:                         pan_dx = round(random.choice((-1, 1)) * amp, 4)
1389:                         pan_dy = round(random.choice((0, 0, 1, -1)) * amp * 0.5, 4)
1390:                 elif edit_profile.enable_paneos:
1391:                     if random.random() < pan_ratio:
1392:                         amp = random.uniform(*pan_amp)
1393:                         pan_dx = round(random.choice((-1, 1)) * amp, 4)
1394:                         pan_dy = round(random.choice((-1, 1)) * amp * 0.5, 4)
1395:                 if pan_dx or pan_dy or (edit_profile.enable_camera_shake and action):
1396:                     if edit_profile.enable_camera_shake and action:
1397:                         shake_amp_x = random.uniform(*shake_amp)
1398:                         shake_amp_y = shake_amp_x * 0.7
1399:                         position_points = _shake_points(
1400:                             duration_us, shake_amp_x, shake_amp_y, pan_dx, pan_dy)
1401:                     else:
1402:                         position_points = _pan_points(duration_us, pan_dx, pan_dy)
1403:                 else:
1404:                     position_points = None
1405:                 if edit_profile.enable_camera_shake and action:
1406:                     zoom_base = cover_scale * getattr(
1407:                         edit_profile, 'shake_zoom_boost', SHAKE_ZOOM_BOOST)
1408:                 else:
1409:                     zoom_base = cover_scale
1410:                 if cover_scale > 1.2:
1411:                     zoom_mult = 1.0
1412:                 refs: list[str] = []
1413:                 dyc_effect_refs: list[str] = list(dyc_shared_effect_refs)
1414:                 if edit_profile.enable_hsl and not dyc_shared_effect_refs:
1415:                     hsl_channels = getattr(edit_profile, 'hsl_channels', HSL_CHANNELS)
1416:                     for channel in hsl_channels:
1417:                         mat = self._hsl_material(channel)
1418:                         hsl_materials.append(mat)
1419:                         refs.append(mat["id"])
1420:                 if edit_profile.enable_color_grading and not dyc_shared_effect_refs:
1421:                     for channel in ADJUST_CHANNELS:
1422:                         mat = self._adjust_material(channel)
1423:                         adjust_materials.append(mat)
1424:                         refs.append(mat["id"])
1425:                 log.info(
1426:                     "Escena %02d · %s: %dx%d → cover=%.3f · zoom=+%.0f%% · %s%s%s",
1427:                     it.order, it.image_path.name, width, height,
1428:                     cover_scale, (zoom_mult - 1.0) * 100,
1429:                     "shake+pan" if (edit_profile.enable_camera_shake and action) else ("pan" if position_points is not None else "fija"),
1430:                     (f" ({pan_dx},{pan_dy})" if position_points is not None else ""),
1431:                     " · hsl" if edit_profile.enable_hsl else "",
1432:                 )
1433:                 mat = self._build_photo_material(
1434:                     content, abs_path, width, height, duration_us, it.image_path.stem)
1435:                 photo_materials.append(mat)
1436:                 video_segments.append(
1437:                     self._build_photo_segment(
1438:                         content, mat["id"], start_us, duration_us, cover_scale, zoom_mult,
1439:                         zoom_base=zoom_base, position_points=position_points,
1440:                         enable_hsl=edit_profile.enable_hsl,
1441:                         enable_adjust=edit_profile.enable_color_grading,
1442:                         extra_refs=refs,
1443:                         fade_in_duration_us=edit_profile.fade_in_duration_us,
1444:                         profile=edit_profile,
1445:                         dyc_effect_refs=dyc_effect_refs))

## 2. Funciones helper llamadas dentro del bucle

### 2.1 _build_photo_material (línea 811-819)

811:     def _build_photo_material(self, content: dict, abs_path: str, width: int,
812:                               height: int, duration_us: int, name: str) -> dict:
813:         mat = copy.deepcopy(canonical.PHOTO_MATERIAL)
814:         mat["id"] = new_id()
815:         mat["unique_id"] = new_id()
816:         mat["path"] = abs_path
817:         mat["duration"] = duration_us
818:         mat["width"] = width
819:         mat["height"] = height
820:         mat["material_name"] = name
821:         return mat

### 2.2 _build_photo_segment (línea 820-848)

820:     def _build_photo_segment(self, content: dict, mat_id: str, start_us: int,
821:                               duration_us: int, cover_scale: float = 1.0,
822:                               zoom_mult: float = 1.0, zoom_base: float = 1.0,
823:                               position_points: list | None = None,
824:                               enable_hsl: bool = True,
825:                               enable_adjust: bool = True,
826:                               extra_refs: list | None = None,
827:                               fade_in_duration_us: int = 0,
828:                               profile: EditProfile | None = None,
829:                               dyc_effect_refs: list | None = None) -> dict:
830:         seg = copy.deepcopy(canonical.PHOTO_SEGMENT)
831:         seg["id"] = new_id()
832:         seg["material_id"] = mat_id
833:         seg["render_index"] = 0
834:         seg["track_render_index"] = 0
835:         seg["source_timerange"] = {"start": 0, "duration": duration_us}
836:         seg["target_timerange"] = {"start": start_us, "duration": duration_us}
837:         seg["clip"]["scale"] = {"x": cover_scale, "y": cover_scale}
838:         seg["uniform_scale"] = {"on": True, "value": 1.0}
839:         kfs = _zoom_keyframes(duration_us, zoom_mult, base=zoom_base)
840:         kfs.extend(_color_keyframes(duration_us, profile))
841:         kfs.extend(_position_entries(position_points))
842:         kfs.extend(_fade_in_keyframes(duration_us, fade_in_duration_us))
843:         seg["common_keyframes"] = kfs
844:         seg["enable_hsl"] = bool(enable_hsl)
845:         seg["enable_adjust"] = bool(enable_adjust)
846:         all_refs = list(dyc_effect_refs or []) + list(extra_refs or [])
847:         seg["extra_material_refs"] = all_refs
848:         return seg

## 3. Output crudo del archivo (líneas 1310-1444)

1310:         for it in items:
1311:             self._check_cancelled()
1312:             if it.image_path is None:
1313:                 log.warning("Escena %d sin imagen; se omite material.", it.order)
1314:                 continue
1315:             start_us = it.start_us if it.duration_us > 0 else prev_end
1316:             duration_us = it.duration_us if it.duration_us > 0 else 1_000_000
1317:             prev_end = start_us + duration_us
1318:             abs_path = it.image_path.resolve().as_posix()
1319:             is_video = it.image_path.suffix.lower() in config.VIDEO_EXTENSIONS
1320:             if is_video:
1321:                 width, height = 1920, 1080
1322:                 try:
1323:                     import subprocess
1324:                     result = subprocess.run(
1325:                         ["ffprobe", "-v", "error",
1326:                          "-show_entries", "format=duration",
1327:                          "-of", "default=noprint_wrappers=1:nokey=1",
1328:                          str(it.image_path)],
1329:                         capture_output=True, text=True, timeout=10,
1330:                     )
1331:                     if result.returncode == 0 and result.stdout.strip():
1332:                         vid_dur_s = float(result.stdout.strip())
1333:                         vid_dur_us = int(round(vid_dur_s * 1_000_000))
1334:                         if vid_dur_us < duration_us:
1335:                             speed = round(vid_dur_us / duration_us, 4)
1336:                             log.info(
1337:                                 "Escena %d · video %s: dur=%d us < frase=%d us → speed=%.4f",
1338:                                 it.order, it.image_path.name, vid_dur_us, duration_us, speed,
1339:                             )
1340:                         else:
1341:                             speed = 1.0
1342:                     else:
1343:                         speed = 1.0
1344:                 except Exception:
1345:                     speed = 1.0
1346:                 cover_scale = 1.0
1347:                 zoom_mult = 1.0
1348:                 zoom_base = 1.0
1349:                 position_points = None
1350:                 refs: list[str] = []
1351:                 enable_hsl = False
1352:                 enable_adjust = False
1353:                 mat = self._build_photo_material(
1354:                     content, abs_path, width, height, duration_us, it.image_path.stem)
1355:                 mat["type"] = "video"
1356:                 photo_materials.append(mat)
1357:                 seg = copy.deepcopy(canonical.VIDEO_TRACK["segments"][0])
1358:                 seg["id"] = new_id()
1359:                 seg["material_id"] = mat["id"]
1360:                 seg["render_index"] = 0
1361:                 seg["track_render_index"] = 0
1362:                 seg["source_timerange"] = {"start": 0, "duration": duration_us}
1363:                 seg["target_timerange"] = {"start": start_us, "duration": duration_us}
1364:                 seg["speed"] = speed
1365:                 seg["clip"]["scale"] = {"x": cover_scale, "y": cover_scale}
1366:                 seg["uniform_scale"] = {"on": True, "value": 1.0}
1367:                 seg["common_keyframes"] = []
1368:                 seg["enable_hsl"] = False
1369:                 seg["enable_adjust"] = False
1370:                 seg["extra_material_refs"] = []
1371:                 video_segments.append(seg)
1372:             else:
1373:                 width, height = _image_size(it.image_path)
1374:                 cover_scale = _cover_scale(canvas_w, canvas_h, width, height)
1375:                 zoom_min = edit_profile.zoom_end_min
1376:                 zoom_max = edit_profile.zoom_end_max
1377:                 zoom_mult = random.uniform(zoom_min, zoom_max)
1378:                 action = _has_action_keyword(it.scene_text) or _has_action_keyword(it.segment_text)
1379:                 pan_ratio = getattr(edit_profile, 'pan_ratio', PAN_RATIO)
1380:                 pan_amp = getattr(edit_profile, 'pan_amplitude', PAN_AMPLITUDE)
1381:                 shake_ratio = getattr(edit_profile, 'shake_ratio', 1.0)
1382:                 shake_amp = getattr(edit_profile, 'shake_amplitude', SHAKE_AMPLITUDE)
1383:                 shake_boost = getattr(edit_profile, 'shake_zoom_boost', SHAKE_ZOOM_BOOST)
1384:                 pan_dx = pan_dy = 0.0
1385:                 if edit_profile.enable_camera_shake and action:
1386:                     if random.random() < pan_ratio:
1387:                         amp = random.uniform(*pan_amp)
1388:                         pan_dx = round(random.choice((-1, 1)) * amp, 4)
1389:                         pan_dy = round(random.choice((0, 0, 1, -1)) * amp * 0.5, 4)
1390:                 elif edit_profile.enable_paneos:
1391:                     if random.random() < pan_ratio:
1392:                         amp = random.uniform(*pan_amp)
1393:                         pan_dx = round(random.choice((-1, 1)) * amp, 4)
1394:                         pan_dy = round(random.choice((-1, 1)) * amp * 0.5, 4)
1395:                 if pan_dx or pan_dy or (edit_profile.enable_camera_shake and action):
1396:                     if edit_profile.enable_camera_shake and action:
1397:                         shake_amp_x = random.uniform(*shake_amp)
1398:                         shake_amp_y = shake_amp_x * 0.7
1399:                         position_points = _shake_points(
1400:                             duration_us, shake_amp_x, shake_amp_y, pan_dx, pan_dy)
1401:                     else:
1402:                         position_points = _pan_points(duration_us, pan_dx, pan_dy)
1403:                 else:
1404:                     position_points = None
1405:                 if edit_profile.enable_camera_shake and action:
1406:                     zoom_base = cover_scale * getattr(
1407:                         edit_profile, 'shake_zoom_boost', SHAKE_ZOOM_BOOST)
1408:                 else:
1409:                     zoom_base = cover_scale
1410:                 if cover_scale > 1.2:
1411:                     zoom_mult = 1.0
1412:                 refs: list[str] = []
1413:                 dyc_effect_refs: list[str] = list(dyc_shared_effect_refs)
1414:                 if edit_profile.enable_hsl and not dyc_shared_effect_refs:
1415:                     hsl_channels = getattr(edit_profile, 'hsl_channels', HSL_CHANNELS)
1416:                     for channel in hsl_channels:
1417:                         mat = self._hsl_material(channel)
1418:                         hsl_materials.append(mat)
1419:                         refs.append(mat["id"])
1420:                 if edit_profile.enable_color_grading and not dyc_shared_effect_refs:
1421:                     for channel in ADJUST_CHANNELS:
1422:                         mat = self._adjust_material(channel)
1423:                         adjust_materials.append(mat)
1424:                         refs.append(mat["id"])
1425:                 log.info(
1426:                     "Escena %02d · %s: %dx%d → cover=%.3f · zoom=+%.0f%% · %s%s%s",
1427:                     it.order, it.image_path.name, width, height,
1428:                     cover_scale, (zoom_mult - 1.0) * 100,
1429:                     "shake+pan" if (edit_profile.enable_camera_shake and action) else ("pan" if position_points is not None else "fija"),
1430:                     (f" ({pan_dx},{pan_dy})" if position_points is not None else ""),
1431:                     " · hsl" if edit_profile.enable_hsl else "",
1432:                 )
1433:                 mat = self._build_photo_material(
1434:                     content, abs_path, width, height, duration_us, it.image_path.stem)
1435:                 photo_materials.append(mat)
1436:                 video_segments.append(
1437:                     self._build_photo_segment(
1438:                         content, mat["id"], start_us, duration_us, cover_scale, zoom_mult,
1439:                         zoom_base=zoom_base, position_points=position_points,
1440:                         enable_hsl=edit_profile.enable_hsl,
1441:                         enable_adjust=edit_profile.enable_color_grading,
1442:                         extra_refs=refs,
1443:                         fade_in_duration_us=edit_profile.fade_in_duration_us,
1444:                         profile=edit_profile,
1445:                         dyc_effect_refs=dyc_effect_refs))