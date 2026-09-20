import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. stopAllAudio
# Look for stopAllAudio definition and update it
stop_audio_old = '''function stopAllAudio() {
        const audios = document.querySelectorAll('audio');
        audios.forEach(a => {
          a.pause();
          a.currentTime = 0;
          a.src = '';
        });
      }'''
      
stop_audio_new = '''function stopAllAudio() {
        const audios = document.querySelectorAll('audio');
        audios.forEach(a => {
          a.pause();
          a.currentTime = 0;
          a.src = '';
        });
        if (typeof clipAudio !== 'undefined' && clipAudio) {
            clipAudio.pause();
            clipAudio.currentTime = 0;
        }
        if (typeof recAudio !== 'undefined' && recAudio) {
            recAudio.pause();
            recAudio.currentTime = 0;
        }
      }'''
text = text.replace(stop_audio_old, stop_audio_new)

# 2. Add regex validation to saveUserIdentity
save_id_old = '''    if (!name) {
      nameEl?.focus();
      showToast('Enter a display name to save your reading.');
      return;
    }

    if (btn) { btn.innerHTML = '<span class="label">Saving…</span>'; btn.disabled = true; }'''

save_id_new = '''    if (!name || name.length <= 1) {
      nameEl?.focus();
      showToast('Enter a valid display name (at least 2 characters).');
      return;
    }

    if (email) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        emailEl?.focus();
        showToast('Please enter a valid email address.');
        return;
      }
    }

    if (btn) { btn.innerHTML = '<span class="label">Saving…</span>'; btn.disabled = true; }'''
text = text.replace(save_id_old, save_id_new)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated index.html")
