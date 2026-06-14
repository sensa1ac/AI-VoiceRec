import time
import threading
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import keyboard as kbd
import pyperclip
import os
import sys

# --- НАСТРОЙКИ ---
MODEL_SIZE = "small" 
SAMPLE_RATE = 16000

def get_model_path():
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, 'model_small')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model_small')

class DictationApp:
    def __init__(self):
        print(f"Загрузка модели '{MODEL_SIZE}'...")
        abs_model_path = get_model_path()
        print(f"Путь к модели: {abs_model_path}")

        # ЗАЩИТА 1: Проверка наличия модели
        if not os.path.exists(abs_model_path):
            print(f"[КРИТИЧЕСКАЯ ОШИБКА] Папка с моделью не найдена по пути: {abs_model_path}")
            print("Убедитесь, что папка 'model_small' находится рядом с программой.")
            time.sleep(10)
            sys.exit(1)

        try:
            self.model = WhisperModel(abs_model_path, device="cpu", compute_type="int8", local_files_only=True) 
            print("Модель успешно загружена и готова к работе!\n")
        except Exception as e:
            print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось инициализировать модель: {e}")
            time.sleep(10)
            sys.exit(1)

        self.is_recording = False
        self.audio_data = []
        self.stream = None
        self.lock = threading.Lock()

    def start_recording(self):
        with self.lock:
            if self.is_recording:
                return
            
            self.is_recording = True
            self.audio_data = []
            
            try:
                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype='float32',
                    callback=self.audio_callback
                )
                self.stream.start()
                print("[REC] Запись пошла (говорите)...")
                
            except Exception as e:
                self.is_recording = False
                print(f"[ОШИБКА АУДИО] Нет доступа к микрофону: {e}")

    def stop_recording(self):
        with self.lock:
            if not self.is_recording:
                return
            
            self.is_recording = False
            print("[STOP] Кнопки отпущены, распознаю...")

            # ЗАЩИТА 2: Безопасное закрытие потока
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception as e:
                    print(f"[ОШИБКА АУДИО] Сбой при закрытии микрофона: {e}")
                finally:
                    self.stream = None

            self.process_audio()

    def audio_callback(self, indata, frames, time_info, status):
        # Игнорируем мелкие системные лаги аудио (overflow)
        if self.is_recording:
            self.audio_data.append(indata.copy())

    def process_audio(self):
        if not self.audio_data:
            return

        audio_np = np.concatenate(self.audio_data, axis=0).flatten()

        if len(audio_np) < SAMPLE_RATE * 0.5:
            print("Слишком короткая запись, игнорирую.\n")
            return

        try:
            segments, _ = self.model.transcribe(audio_np, beam_size=5, language="ru")
            text = " ".join([segment.text for segment in segments]).strip()

            if text:
                self.type_text(text)
            else:
                print("Тишина. Ничего не распознано.\n")
                
        except Exception as e:
            print(f"[ОШИБКА ИНФЕРЕНСА] Сбой распознавания: {e}\n")

    def type_text(self, text):
        text = text + " "
        print(f"Результат: {text}\n")

        # ЗАЩИТА 3: Броня буфера обмена
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            old_clipboard = "" # Если не смогли прочитать старый буфер, просто игнорируем

        try:
            pyperclip.copy(text)

            kbd.release('ctrl')
            kbd.release(41)
            time.sleep(0.05) 

            kbd.send('ctrl+v')
            
            # Увеличенный тайминг, чтобы тяжелые программы (Word) успели "прожевать" вставку
            time.sleep(0.15) 

            if old_clipboard:
                pyperclip.copy(old_clipboard)
                
        except Exception as e:
            print(f"[ОШИБКА БУФЕРА] Не удалось вставить текст: {e}\n")


if __name__ == "__main__":
    # ЗАЩИТА 4: Глобальный отлов фатальных сбоев на старте
    try:
        app = DictationApp()
        print(">>> Программа активна.")
        print(">>> ЗАЖМИТЕ [Ctrl + Кнопка под ESC (ё/`)], продиктуйте фразу и отпустите.\n")
    except Exception as e:
        print(f"Фатальная ошибка при запуске: {e}")
        time.sleep(10)
        sys.exit(1)

    while True:
        # ЗАЩИТА 5: Броня главного цикла и Watchdog
        try:
            loop_start = time.time()

            if kbd.is_pressed('ctrl') and kbd.is_pressed(41):
                app.start_recording()
                record_start = time.time()
                
                while kbd.is_pressed('ctrl') and kbd.is_pressed(41):
                    time.sleep(0.05)
                    
                    # ЗАЩИТА ОТ ЗАЛИПАНИЯ (максимум 3 минуты записи)
                    if time.time() - record_start > 180:
                        print("[WATCHDOG] Превышен лимит записи (3 мин). Принудительный стоп.")
                        break 
                        
                app.stop_recording()
                
            time.sleep(0.05)
            
            # ЗАЩИТА ОТ СНА (Если цикл спал больше 3 секунд)
            if time.time() - loop_start > 3.0:
                print("[WATCHDOG] Обнаружен выход из режима сна. Сброс хуков...")
                kbd.unhook_all()
            
        except Exception as e:
            print(f"[СИСТЕМНАЯ ОШИБКА] Сбой в главном цикле: {e}")
            try:
                kbd.unhook_all() # Освобождаем клавиатуру при жестком краше цикла
            except:
                pass
            time.sleep(1) # Ждем секунду, чтобы избежать спама в консоль, и продолжаем
