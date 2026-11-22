// 临时集成验证器：直接调用 rg-core 的 apply_action，验证按钮→core→docker 链路。
use rg_core::{apply_action, config::LauncherConfig, Action};

fn main() {
    let config = LauncherConfig::discover().expect("项目根定位失败");
    let action = std::env::args().nth(1).expect("用法: rg-verify <refresh|logs|stop|start|restart>");
    let act = match action.as_str() {
        "refresh" => Action::Refresh,
        "logs" => Action::Logs,
        "stop" => Action::Stop,
        "start" => Action::Start,
        "restart" => Action::Restart,
        _ => panic!("未知 action: {action}"),
    };
    match apply_action(act, &config) {
        Ok(msg) => {
            let short: String = msg.chars().take(300).collect();
            println!("OK[{action}]: {short}");
        }
        Err(err) => {
            eprintln!("ERR[{action}]: {err}");
            std::process::exit(1);
        }
    }
}
