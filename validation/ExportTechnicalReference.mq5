// Read-only reference exporter. No orders, account data, DLLs, or network calls.
#property script_show_inputs
input string Symbols = "XAUUSD_i,BTCUSD,GBPUSD_i,EURUSD_i";
input int Count = 2000;
void OnStart()
{
   int meta=FileOpen("companion-clock.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(meta==INVALID_HANDLE) return;
   FileWrite(meta,"gmt","trade_server","build");
   FileWrite(meta,(long)TimeGMT(),(long)TimeTradeServer(),TerminalInfoInteger(TERMINAL_BUILD));
   FileClose(meta);
   string names[]; StringSplit(Symbols,',',names);
   ENUM_TIMEFRAMES frames[]={PERIOD_M5,PERIOD_M15,PERIOD_H1,PERIOD_H4};
   int file=FileOpen("companion-reference.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(file==INVALID_HANDLE) return;
   FileWrite(file,"symbol","timeframe","bar_open_server","open","high","low","close","tick_volume","ema20","ema50","atr14");
   for(int s=0;s<ArraySize(names);s++)
   {
      if(!SymbolSelect(names[s],true)) continue;
      for(int t=0;t<ArraySize(frames);t++)
      {
         int fast=iMA(names[s],frames[t],20,0,MODE_EMA,PRICE_CLOSE);
         int slow=iMA(names[s],frames[t],50,0,MODE_EMA,PRICE_CLOSE);
         int atr=iATR(names[s],frames[t],14);
         MqlRates rates[]; double f[],v[],a[];
         int n=0;
         for(int attempt=0;attempt<20;attempt++)
         {
            n=CopyRates(names[s],frames[t],1,Count,rates);
            if(n>250 && CopyBuffer(fast,0,rates[0].time,rates[n-1].time,f)==n &&
               CopyBuffer(slow,0,rates[0].time,rates[n-1].time,v)==n &&
               CopyBuffer(atr,0,rates[0].time,rates[n-1].time,a)==n) break;
            n=0; Sleep(500);
         }
         for(int i=0;i<n;i++)
            FileWrite(file,names[s],EnumToString(frames[t]),(long)rates[i].time,
                      DoubleToString(rates[i].open,12),DoubleToString(rates[i].high,12),
                      DoubleToString(rates[i].low,12),DoubleToString(rates[i].close,12),rates[i].tick_volume,
                      DoubleToString(f[i],12),DoubleToString(v[i],12),DoubleToString(a[i],12));
         IndicatorRelease(fast); IndicatorRelease(slow); IndicatorRelease(atr);
      }
   }
   FileClose(file);
   Print("Companion read-only reference export completed.");
}
