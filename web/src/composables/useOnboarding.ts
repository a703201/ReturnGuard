/** 首次部署引导共享状态：首次进入自动弹出，也可从设置页重新打开。 */
import { ref } from 'vue'

const KEY = 'rg.onboarded'
export const onboardingOpen = ref(false)

export function shouldShowOnboarding(): boolean {
  try { return !localStorage.getItem(KEY) } catch { return false }
}
export function openOnboarding() { onboardingOpen.value = true }
export function closeOnboarding() { onboardingOpen.value = false }
