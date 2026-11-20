/** 登录弹层共享开关：顶栏与设置页打开同一个 Sheet，避免两套登录入口。 */
import { ref } from 'vue'

export const loginSheetOpen = ref(false)
export function openLoginSheet() { loginSheetOpen.value = true }
export function closeLoginSheet() { loginSheetOpen.value = false }
