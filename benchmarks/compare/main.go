// Benchmark adapter: common-format parsing + aggregation + signatures + spikes,
// two full scans and raw-byte SHA256. No CLI report/context rendering on either side.
package main
import("bufio";"crypto/sha256";"encoding/hex";"encoding/json";"fmt";"io";"os";"regexp";"sort";"strings";"time")
type Record struct{Ts string `json:"ts"`;Level string `json:"level"`;Msg string `json:"msg"`}
var digits=regexp.MustCompile(`[0-9]+`)
func parse(s string)(int64,string,string){
 r:=Record{}; if strings.HasPrefix(s,"{"){if json.Unmarshal([]byte(s),&r)!=nil{return -1,"OTHER",s}}else{if len(s)<23{return -1,"OTHER",s};r.Ts=s[:19];end:=strings.Index(s[21:],"]");if s[20]!='['||end<0{return -1,"OTHER",s};end+=21;r.Level=s[21:end];r.Msg=strings.TrimLeft(s[end+1:]," ")}
 level:=r.Level;switch level{case "DEBUG","INFO","WARN","ERROR","FATAL":default:level="OTHER"}
 t,err:=time.Parse("2006-01-02 15:04:05",r.Ts);if err!=nil{return -1,level,r.Msg};return t.Unix()/60+1035593280,level,r.Msg
}
func main(){if len(os.Args)!=2{panic("input required")};buckets:=map[int64][]int64{};levels:=map[string]int64{};for _,s:=range []string{"DEBUG","INFO","WARN","ERROR","FATAL","OTHER"}{levels[s]=0};sig:=map[string]int64{};var total,untimed int64;first,last:=int64(-1),int64(-1);hashes:=[]string{}
for pass:=0;pass<2;pass++{f,e:=os.Open(os.Args[1]);if e!=nil{panic(e)};h:=sha256.New();scan:=bufio.NewScanner(io.TeeReader(f,h));scan.Buffer(make([]byte,65536),65537);for scan.Scan(){line:=strings.TrimSuffix(scan.Text(),"\r");m,l,msg:=parse(line);if pass==1{continue};total++;levels[l]++;errorLine:=l=="ERROR"||l=="FATAL";if errorLine{k:=l+": "+digits.ReplaceAllString(msg,"#");sig[k]++};if m<0{untimed++;continue};m=m/5*5;if first<0||m<first{first=m};if m>last{last=m};if buckets[m]==nil{buckets[m]=[]int64{m,0,0}};buckets[m][1]++;if errorLine{buckets[m][2]++}};if scan.Err()!=nil{panic(scan.Err())};f.Close();hashes=append(hashes,hex.EncodeToString(h.Sum(nil)))};if hashes[0]!=hashes[1]{panic("input changed")}
bs:=[][]int64{};for m:=first;m>=0&&m<=last;m+=5{b:=buckets[m];if b==nil{b=[]int64{m,0,0}};bs=append(bs,b)}
spikes:=[][]any{};var sum int64;for i,b:=range bs{if i>=6{if b[2]>=3&&(sum==0||b[2]*6>3*sum){n:=len(spikes);if n>0&&spikes[n-1][1].(int64)==b[0]{s:=spikes[n-1];s[1]=b[0]+5;s[2]=s[2].(int64)+b[2];if b[2]>s[3].(int64){s[3]=b[2]}}else{spikes=append(spikes,[]any{b[0],b[0]+5,b[2],b[2],float64(sum)/6})}};sum-=bs[i-6][2]};sum+=b[2]}
keys:=[]string{};for k:=range sig{keys=append(keys,k)};sort.Slice(keys,func(i,j int)bool{if sig[keys[i]]==sig[keys[j]]{return keys[i]<keys[j]};return sig[keys[i]]>sig[keys[j]]});ss:=[][]any{};for _,k:=range keys{ss=append(ss,[]any{k,sig[k]})};out,e:=json.Marshal(map[string]any{"total":total,"untimed":untimed,"levels":levels,"sha256":hashes[0],"buckets":bs,"spikes":spikes,"signatures":ss});if e!=nil{panic(e)};fmt.Println(string(out))}
