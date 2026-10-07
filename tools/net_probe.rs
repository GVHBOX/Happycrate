use happycrate::net;

fn main() {
    let resolved = net::resolve("");
    println!("模式      : {}", resolved.mode);
    println!("地址      : {}", resolved.addr);
    println!("映射      : {:?}", resolved.mapping);
    println!("绕过条目  : {}", resolved.overrides.split(';').count());
    for host in ["apibay.org", "127.0.0.1", "192.168.1.5", "localhost"] {
        println!("绕过 {:>14} : {}", host, net::bypass(host, &resolved));
    }
    println!("TUN 适配器: {:?}", net::scan_tun_adapter());
    println!("环境变量  : {:?}", net::env_proxies());
    println!("注册表    : {:?}", net::registry_proxies());
}
